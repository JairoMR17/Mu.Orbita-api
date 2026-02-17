#!/usr/bin/env python3
"""
Mu.Orbita GEE Automation Script v4 (WEB-READY)
==============================================

NOVEDADES V4:
✅ Export PNG visualizados (listos para dashboard web)
✅ Bounds incluidos en KPIs para posicionar en Leaflet
✅ VRA zonificación (k-means 3 zonas)
✅ Stats por zona VRA
✅ Carpetas organizadas (WEB, TIFF, DATA, VRA)
✅ Mantiene GeoTIFFs para análisis

Uso:
    python gee_automation_v4.py --mode execute --job-id JOB_123 --roi '{"type":"Polygon",...}'
"""

import argparse
import json
import ee
import sys
import os
from datetime import datetime, timedelta

# ============================================================================
# INICIALIZACIÓN
# ============================================================================

def initialize_gee():
    """Initialize Earth Engine with Service Account or default credentials"""
    try:
        service_account_key = os.environ.get('GEE_SERVICE_ACCOUNT_KEY')
        if service_account_key:
            key_data = json.loads(service_account_key)
            credentials = ee.ServiceAccountCredentials(
                email=key_data['client_email'],
                key_data=service_account_key
            )
            ee.Initialize(credentials)
        else:
            ee.Initialize()
        return True
    except Exception as e:
        print(json.dumps({"error": f"Failed to initialize GEE: {str(e)}"}))
        return False

if not initialize_gee():
    sys.exit(1)

# ============================================================================
# PALETAS DE VISUALIZACIÓN (para PNGs)
# ============================================================================

VIZ_PALETTES = {
    'NDVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000', 'FF0000', 'FF6347', 'FFA500', 'FFFF00', 
                    'ADFF2F', '7CFC00', '32CD32', '228B22', '006400']
    },
    'NDWI': {
        'min': -0.3, 'max': 0.4,
        'palette': ['8B4513', 'D2691E', 'F4A460', 'FFF8DC', 'E0FFFF', 
                    '87CEEB', '4682B4', '0000CD', '00008B']
    },
    'EVI': {
        'min': 0.0, 'max': 0.6,
        'palette': ['8B0000', 'CD5C5C', 'F08080', 'FFFFE0', 'ADFF2F', 
                    '7FFF00', '32CD32', '228B22', '006400']
    },
    'NDCI': {
        'min': -0.2, 'max': 0.6,
        'palette': ['8B0000', 'FF6347', 'FFA500', 'FFFF00', 'ADFF2F', 
                    '7CFC00', '32CD32', '228B22', '006400']
    },
    'SAVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000', 'FF0000', 'FF6347', 'FFA500', 'FFFF00', 
                    'ADFF2F', '7CFC00', '32CD32', '228B22', '006400']
    },
    'VRA': {
        'min': 0, 'max': 2,
        'palette': ['e74c3c', 'f1c40f', '27ae60']  # Rojo, Amarillo, Verde
    },
    'LST': {
        'min': 15, 'max': 45,
        'palette': ['0000FF', '00FFFF', '00FF00', 'FFFF00', 'FF0000']
    }
}

# ============================================================================
# ARGUMENTOS
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description='Mu.Orbita GEE Automation v4 (Web-Ready)')
    parser.add_argument('--mode', required=True, 
                        choices=['execute', 'check-status', 'download-results', 'start-tasks'])
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--roi', help='GeoJSON string of ROI')
    parser.add_argument('--start-date', help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', help='End date YYYY-MM-DD')
    parser.add_argument('--crop', default='olivar', help='Crop type')
    parser.add_argument('--buffer', type=int, default=0, help='Buffer in meters')
    parser.add_argument('--analysis-type', default='baseline', help='Type of analysis')
    parser.add_argument('--drive-folder', default='MuOrbita_Outputs', help='Google Drive base folder')
    parser.add_argument('--output-dir', help='Local output directory')
    parser.add_argument('--export-png', type=bool, default=True, help='Export PNG for web dashboard')
    return parser.parse_args()

# ============================================================================
# UTILIDADES
# ============================================================================

def create_roi(geojson_str, buffer_meters=0):
    """Create EE geometry from GeoJSON"""
    try:
        geojson = json.loads(geojson_str)
        if geojson.get('type') == 'FeatureCollection':
            roi = ee.FeatureCollection(geojson).geometry()
        elif geojson.get('type') == 'Feature':
            roi = ee.Geometry(geojson['geometry'])
        else:
            roi = ee.Geometry(geojson)
        
        if buffer_meters > 0:
            roi = roi.buffer(buffer_meters)
        return roi
    except Exception as e:
        raise ValueError(f"Invalid GeoJSON: {str(e)}")


def get_bounds(roi):
    """Get bounds of ROI for Leaflet positioning"""
    try:
        bounds = roi.bounds().coordinates().getInfo()[0]
        # bounds es [[west, south], [west, north], [east, north], [east, south], [west, south]]
        lngs = [p[0] for p in bounds]
        lats = [p[1] for p in bounds]
        return {
            'south': min(lats),
            'west': min(lngs),
            'north': max(lats),
            'east': max(lngs)
        }
    except Exception as e:
        print(f"Warning: Could not get bounds: {e}")
        return None

# ============================================================================
# COLECCIONES DE DATOS
# ============================================================================

def get_sentinel2_collection(roi, start_date, end_date):
    """Get Sentinel-2 SR collection with cloud masking"""
    def mask_clouds(image):
        qa = image.select('QA60')
        scl = image.select('SCL')
        
        cloud_mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
        scl_mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
        
        return image.updateMask(cloud_mask.And(scl_mask)).divide(10000).copyProperties(image, ['system:time_start'])
    
    collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
        .map(mask_clouds))
    
    return collection


def calculate_indices(image):
    """Calculate all vegetation indices"""
    nir = image.select('B8')
    red = image.select('B4')
    blue = image.select('B2')
    swir = image.select('B11')
    red_edge = image.select('B5')
    
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndwi = image.normalizedDifference(['B8', 'B11']).rename('NDWI')
    
    evi = image.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {'NIR': nir, 'RED': red, 'BLUE': blue}
    ).rename('EVI')
    
    ndci = image.normalizedDifference(['B5', 'B4']).rename('NDCI')
    
    # SAVI (Soil Adjusted Vegetation Index)
    L = 0.5
    savi = nir.subtract(red).divide(nir.add(red).add(L)).multiply(1 + L).rename('SAVI')
    
    # OSAVI (Optimized for olive groves)
    osavi = nir.subtract(red).divide(nir.add(red).add(0.16)).multiply(1.16).rename('OSAVI')
    
    return image.addBands([ndvi, ndwi, evi, ndci, savi, osavi])


def get_modis_lst(roi, start_date, end_date):
    """Get MODIS Land Surface Temperature"""
    modis = (ee.ImageCollection('MODIS/061/MOD11A2')
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .select('LST_Day_1km')
        .map(lambda img: img.multiply(0.02).subtract(273.15).rename('LST_C')
             .copyProperties(img, ['system:time_start'])))
    
    return modis.median().clip(roi)

# ============================================================================
# VRA ZONIFICACIÓN
# ============================================================================

def calculate_vra_zones(composite, roi):
    """Calculate VRA zones using k-means clustering"""
    try:
        # Bandas para clustering
        training_bands = ['NDVI', 'EVI', 'NDWI']
        training_image = composite.select(training_bands)
        
        # Máscara de píxeles válidos
        valid_mask = training_image.mask().reduce(ee.Reducer.min())
        training_masked = training_image.updateMask(valid_mask)
        
        # Sample para entrenar clusterer
        sample = training_masked.sample(
            region=roi,
            scale=20,
            numPixels=5000,
            geometries=False
        )
        
        # K-means con 3 clusters
        clusterer = ee.Clusterer.wekaKMeans(3).train(sample)
        vra = training_masked.cluster(clusterer).rename('zone')
        
        # Calcular stats por zona
        vra_with_ndvi = vra.addBands(composite.select(['NDVI', 'NDWI', 'EVI']))
        
        vra_stats = []
        for zone_num in range(3):
            zone_mask = vra.eq(zone_num)
            zone_area = zone_mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=roi,
                scale=20,
                maxPixels=1e9
            ).getInfo()
            
            zone_indices = composite.select(['NDVI', 'NDWI', 'EVI']).updateMask(zone_mask).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=20,
                maxPixels=1e9
            ).getInfo()
            
            area_ha = zone_area.get('zone', 0) / 10000
            vra_stats.append({
                'zone': zone_num,
                'area_ha': round(area_ha, 2),
                'ndvi_mean': round(zone_indices.get('NDVI', 0) or 0, 3),
                'ndwi_mean': round(zone_indices.get('NDWI', 0) or 0, 3),
                'evi_mean': round(zone_indices.get('EVI', 0) or 0, 3)
            })
        
        # Ordenar por NDVI para asignar labels
        vra_stats.sort(key=lambda x: x['ndvi_mean'])
        labels = ['Bajo vigor', 'Vigor medio', 'Alto vigor']
        recommendations = ['Dosis alta', 'Dosis media', 'Dosis baja']
        
        for i, stat in enumerate(vra_stats):
            stat['label'] = labels[i]
            stat['recommendation'] = recommendations[i]
        
        return vra, vra_stats
        
    except Exception as e:
        print(f"Warning: VRA calculation failed: {e}")
        return None, []

# ============================================================================
# EJECUTAR ANÁLISIS
# ============================================================================

def execute_analysis(args):
    """Execute GEE analysis and start export tasks"""
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    
    # Carpetas de salida organizadas
    base_folder = f"{args.drive_folder}/{job_id}"
    folders = {
        'web': f"{base_folder}/WEB",      # PNGs para dashboard
        'tiff': f"{base_folder}/TIFF",    # GeoTIFFs para análisis
        'data': f"{base_folder}/DATA",    # CSVs
        'vra': f"{base_folder}/VRA"       # Zonificación
    }
    
    # Get bounds para posicionamiento web
    bounds = get_bounds(roi)
    
    # Get Sentinel-2 collection
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    
    if count == 0:
        return {
            "error": "No images found for the specified date range and ROI",
            "job_id": job_id,
            "start_date": args.start_date,
            "end_date": args.end_date
        }
    
    # Calculate indices and create composite
    indexed_collection = collection.map(calculate_indices)
    composite = indexed_collection.median().clip(roi)
    
    # Get latest image date
    latest = collection.sort('system:time_start', False).first()
    try:
        latest_date = ee.Date(latest.get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date
    
    # Calculate comprehensive statistics
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI', 'OSAVI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True),
        geometry=roi,
        scale=10,
        maxPixels=1e9
    ).getInfo()
    
    # Calculate area
    area_ha = roi.area().divide(10000).getInfo()
    
    # Calculate stress area (NDVI < 0.35)
    stress_mask = composite.select('NDVI').lt(0.35)
    stress_area = stress_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=roi,
        scale=10,
        maxPixels=1e9
    ).getInfo()
    stress_ha = stress_area.get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0
    
    # Z-score calculation
    hist_stats = indexed_collection.select('NDVI').mean().reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi,
        scale=20,
        maxPixels=1e9
    ).getInfo()
    
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0
    
    # Get MODIS LST
    try:
        lst = get_modis_lst(roi, args.start_date, args.end_date)
        lst_stats = lst.reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True),
            geometry=roi,
            scale=1000,
            maxPixels=1e9
        ).getInfo()
        lst_mean = lst_stats.get('LST_C_mean', None)
        lst_min = lst_stats.get('LST_C_min', None)
        lst_max = lst_stats.get('LST_C_max', None)
    except:
        lst = None
        lst_mean = lst_min = lst_max = None
    
    # Calculate VRA zones
    vra_image, vra_stats = calculate_vra_zones(composite, roi)
    
    # Build comprehensive KPIs (including bounds for web)
    kpis = {
        'job_id': job_id,
        'crop_type': args.crop,
        'analysis_type': args.analysis_type,
        'start_date': args.start_date,
        'end_date': args.end_date,
        'latest_image_date': latest_date,
        'images_processed': count,
        'area_hectares': round(area_ha, 2),
        
        # NDVI
        'ndvi_mean': round(stats.get('NDVI_mean', 0) or 0, 3),
        'ndvi_p10': round(stats.get('NDVI_p10', 0) or 0, 3),
        'ndvi_p50': round(stats.get('NDVI_p50', 0) or 0, 3),
        'ndvi_p90': round(stats.get('NDVI_p90', 0) or 0, 3),
        'ndvi_stddev': round(stats.get('NDVI_stdDev', 0) or 0, 3),
        'ndvi_zscore': round(z_score, 2),
        
        # NDWI
        'ndwi_mean': round(stats.get('NDWI_mean', 0) or 0, 3),
        'ndwi_p10': round(stats.get('NDWI_p10', 0) or 0, 3),
        'ndwi_p90': round(stats.get('NDWI_p90', 0) or 0, 3),
        
        # EVI
        'evi_mean': round(stats.get('EVI_mean', 0) or 0, 3),
        'evi_p10': round(stats.get('EVI_p10', 0) or 0, 3),
        'evi_p90': round(stats.get('EVI_p90', 0) or 0, 3),
        
        # NDCI
        'ndci_mean': round(stats.get('NDCI_mean', 0) or 0, 3),
        
        # SAVI / OSAVI
        'savi_mean': round(stats.get('SAVI_mean', 0) or 0, 3),
        'osavi_mean': round(stats.get('OSAVI_mean', 0) or 0, 3),
        
        # Stress
        'stress_area_ha': round(stress_ha, 2),
        'stress_area_pct': round(stress_pct, 1),
        
        # Thermal (MODIS LST)
        'lst_mean_c': round(lst_mean, 1) if lst_mean else None,
        'lst_min_c': round(lst_min, 1) if lst_min else None,
        'lst_max_c': round(lst_max, 1) if lst_max else None,
        
        # Bounds for web positioning (Leaflet)
        'bounds_south': bounds['south'] if bounds else None,
        'bounds_west': bounds['west'] if bounds else None,
        'bounds_north': bounds['north'] if bounds else None,
        'bounds_east': bounds['east'] if bounds else None,
        
        # Quality
        'valid_pixels': stats.get('NDVI_count', 0)
    }
    
    # ========== EXPORT TASKS ==========
    tasks = []
    
    # ---------- PNG EXPORTS (Web Dashboard) ----------
    if args.export_png:
        indices_to_export_png = ['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI']
        
        for idx_name in indices_to_export_png:
            viz = VIZ_PALETTES[idx_name]
            visualized = composite.select(idx_name).visualize(**viz)
            
            task = ee.batch.Export.image.toDrive(
                image=visualized,
                description=f'{job_id}_PNG_{idx_name}',
                folder=folders['web'],
                fileNamePrefix=f'PNG_{idx_name}',
                region=roi,
                scale=10,
                maxPixels=1e9,
                fileFormat='PNG'
            )
            task.start()
            tasks.append({
                'name': f'PNG_{idx_name}.png',
                'type': f'png_{idx_name.lower()}',
                'id': task.id,
                'folder': 'WEB'
            })
        
        # PNG VRA
        if vra_image is not None:
            viz_vra = VIZ_PALETTES['VRA']
            vra_visualized = vra_image.visualize(**viz_vra)
            
            task_vra_png = ee.batch.Export.image.toDrive(
                image=vra_visualized,
                description=f'{job_id}_PNG_VRA',
                folder=folders['web'],
                fileNamePrefix='PNG_VRA',
                region=roi,
                scale=10,
                maxPixels=1e9,
                fileFormat='PNG'
            )
            task_vra_png.start()
            tasks.append({
                'name': 'PNG_VRA.png',
                'type': 'png_vra',
                'id': task_vra_png.id,
                'folder': 'WEB'
            })
        
        # PNG LST
        if lst is not None:
            viz_lst = VIZ_PALETTES['LST']
            lst_visualized = lst.visualize(**viz_lst)
            
            task_lst_png = ee.batch.Export.image.toDrive(
                image=lst_visualized,
                description=f'{job_id}_PNG_LST',
                folder=folders['web'],
                fileNamePrefix='PNG_LST',
                region=roi,
                scale=250,  # MODIS resolution
                maxPixels=1e9,
                fileFormat='PNG'
            )
            task_lst_png.start()
            tasks.append({
                'name': 'PNG_LST.png',
                'type': 'png_lst',
                'id': task_lst_png.id,
                'folder': 'WEB'
            })
    
    # ---------- GEOTIFF EXPORTS (Analysis) ----------
    indices_to_export_tiff = ['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI', 'OSAVI']
    
    for idx_name in indices_to_export_tiff:
        task = ee.batch.Export.image.toDrive(
            image=composite.select(idx_name),
            description=f'{job_id}_TIFF_{idx_name}',
            folder=folders['tiff'],
            fileNamePrefix=f'TIFF_{idx_name}',
            region=roi,
            scale=10,
            maxPixels=1e9,
            fileFormat='GeoTIFF'
        )
        task.start()
        tasks.append({
            'name': f'TIFF_{idx_name}.tif',
            'type': f'tiff_{idx_name.lower()}',
            'id': task.id,
            'folder': 'TIFF'
        })
    
    # ---------- VRA EXPORTS ----------
    if vra_image is not None:
        # VRA Raster
        task_vra_tiff = ee.batch.Export.image.toDrive(
            image=vra_image.byte(),
            description=f'{job_id}_VRA_RASTER',
            folder=folders['vra'],
            fileNamePrefix='VRA_RASTER',
            region=roi,
            scale=10,
            maxPixels=1e9,
            fileFormat='GeoTIFF'
        )
        task_vra_tiff.start()
        tasks.append({
            'name': 'VRA_RASTER.tif',
            'type': 'vra_raster',
            'id': task_vra_tiff.id,
            'folder': 'VRA'
        })
        
        # VRA Vector (Shapefile)
        try:
            vra_vectors = vra_image.reduceToVectors(
                geometry=roi,
                scale=20,
                geometryType='polygon',
                labelProperty='zone',
                maxPixels=1e9
            )
            
            task_vra_shp = ee.batch.Export.table.toDrive(
                collection=vra_vectors,
                description=f'{job_id}_VRA_VECTOR',
                folder=folders['vra'],
                fileNamePrefix='VRA_VECTOR',
                fileFormat='SHP'
            )
            task_vra_shp.start()
            tasks.append({
                'name': 'VRA_VECTOR.shp',
                'type': 'vra_vector',
                'id': task_vra_shp.id,
                'folder': 'VRA'
            })
        except Exception as e:
            print(f"Warning: VRA vector export failed: {e}")
        
        # VRA Stats CSV
        vra_stats_feature = ee.FeatureCollection([
            ee.Feature(None, stat) for stat in vra_stats
        ])
        
        task_vra_stats = ee.batch.Export.table.toDrive(
            collection=vra_stats_feature,
            description=f'{job_id}_VRA_STATS',
            folder=folders['vra'],
            fileNamePrefix='VRA_STATS',
            fileFormat='CSV'
        )
        task_vra_stats.start()
        tasks.append({
            'name': 'VRA_STATS.csv',
            'type': 'vra_stats',
            'id': task_vra_stats.id,
            'folder': 'VRA'
        })
    
    # ---------- DATA EXPORTS (CSVs) ----------
    
    # KPIs CSV
    kpi_feature = ee.Feature(None, kpis)
    kpi_collection = ee.FeatureCollection([kpi_feature])
    
    task_kpis = ee.batch.Export.table.toDrive(
        collection=kpi_collection,
        description=f'{job_id}_KPIs',
        folder=folders['data'],
        fileNamePrefix='KPIs',
        fileFormat='CSV'
    )
    task_kpis.start()
    tasks.append({
        'name': 'KPIs.csv',
        'type': 'kpis',
        'id': task_kpis.id,
        'folder': 'DATA'
    })
    
    # Time Series CSV
    ts_features = indexed_collection.select(['NDVI', 'NDWI', 'EVI']).map(lambda img: 
        ee.Feature(None, img.reduceRegion(
            reducer=ee.Reducer.mean()
                .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True),
            geometry=roi,
            scale=20,
            maxPixels=1e9
        )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
    )
    
    task_ts = ee.batch.Export.table.toDrive(
        collection=ee.FeatureCollection(ts_features),
        description=f'{job_id}_TimeSeries',
        folder=folders['data'],
        fileNamePrefix='TimeSeries',
        fileFormat='CSV'
    )
    task_ts.start()
    tasks.append({
        'name': 'TimeSeries.csv',
        'type': 'timeseries',
        'id': task_ts.id,
        'folder': 'DATA'
    })
    
    # Get time series for immediate use
    time_series = []
    try:
        ts_list = ts_features.toList(500).getInfo()
        for feature in ts_list:
            props = feature.get('properties', {})
            if props.get('date'):
                time_series.append({
                    'date': props.get('date', ''),
                    'ndvi': round(props.get('NDVI_mean', 0) or 0, 3),
                    'ndwi': round(props.get('NDWI_mean', 0) or 0, 3),
                    'evi': round(props.get('EVI_mean', 0) or 0, 3)
                })
        time_series.sort(key=lambda x: x['date'])
    except Exception as e:
        print(f"Warning: Could not get time series: {e}")
    
    # Construct image URLs for dashboard
    image_urls = {}
    if bounds:
        for idx in ['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI', 'VRA', 'LST']:
            image_urls[idx] = f"/api/images/{job_id}/PNG_{idx}.png"
    
    # Return result
    result = {
        'success': True,
        'job_id': job_id,
        'kpis': kpis,
        'vra_stats': vra_stats,
        'bounds': bounds,
        'image_urls': image_urls,
        'tasks': tasks,
        'task_count': len(tasks),
        'folders': folders,
        'time_series': time_series,
        'message': f'Analysis complete. {len(tasks)} export tasks started ({len([t for t in tasks if "png" in t["type"]])} PNGs for web).'
    }
    
    return result

# ============================================================================
# CHECK STATUS
# ============================================================================

def check_status(args):
    """Check status of export tasks"""
    tasks = ee.batch.Task.list()
    job_tasks = [t for t in tasks if args.job_id in t.config.get('description', '')]
    
    status = []
    completed = 0
    running = 0
    failed = 0
    pending = 0
    
    for task in job_tasks:
        state = task.state
        status.append({
            'name': task.config.get('description'),
            'state': state,
            'id': task.id
        })
        
        if state == 'COMPLETED':
            completed += 1
        elif state in ['RUNNING', 'READY']:
            running += 1
        elif state == 'FAILED':
            failed += 1
        else:
            pending += 1
    
    total = len(status)
    all_complete = (completed == total and total > 0 and running == 0 and pending == 0)
    
    # Separate PNG tasks for quick check
    png_tasks = [t for t in status if 'PNG' in t['name']]
    png_complete = all(t['state'] == 'COMPLETED' for t in png_tasks) if png_tasks else False
    
    return {
        'job_id': args.job_id,
        'tasks': status,
        'completed': completed,
        'running': running,
        'failed': failed,
        'pending': pending,
        'total': total,
        'all_complete': all_complete,
        'png_complete': png_complete,  # Dashboard can show images when PNGs are ready
        'any_failed': failed > 0,
        'progress_pct': round(completed / total * 100) if total > 0 else 0,
        'message': f'COMPLETED: {completed}, RUNNING: {running}, FAILED: {failed}, PENDING: {pending}'
    }

# ============================================================================
# DOWNLOAD RESULTS
# ============================================================================

def download_results(args):
    """Return info about exported files"""
    status = check_status(args)
    
    if not status['all_complete']:
        return {
            'job_id': args.job_id,
            'status': 'waiting',
            'download_ready': False,
            'png_ready': status.get('png_complete', False),
            'message': 'Tasks not yet complete',
            'progress': status
        }
    
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
    
    job_id = args.job_id
    
    # List of files organized by folder
    files = {
        'WEB': [
            {'name': 'PNG_NDVI.png', 'type': 'png_ndvi'},
            {'name': 'PNG_NDWI.png', 'type': 'png_ndwi'},
            {'name': 'PNG_EVI.png', 'type': 'png_evi'},
            {'name': 'PNG_NDCI.png', 'type': 'png_ndci'},
            {'name': 'PNG_SAVI.png', 'type': 'png_savi'},
            {'name': 'PNG_VRA.png', 'type': 'png_vra'},
            {'name': 'PNG_LST.png', 'type': 'png_lst'},
        ],
        'TIFF': [
            {'name': 'TIFF_NDVI.tif', 'type': 'tiff_ndvi'},
            {'name': 'TIFF_NDWI.tif', 'type': 'tiff_ndwi'},
            {'name': 'TIFF_EVI.tif', 'type': 'tiff_evi'},
            {'name': 'TIFF_NDCI.tif', 'type': 'tiff_ndci'},
            {'name': 'TIFF_SAVI.tif', 'type': 'tiff_savi'},
            {'name': 'TIFF_OSAVI.tif', 'type': 'tiff_osavi'},
        ],
        'DATA': [
            {'name': 'KPIs.csv', 'type': 'kpis'},
            {'name': 'TimeSeries.csv', 'type': 'timeseries'},
        ],
        'VRA': [
            {'name': 'VRA_RASTER.tif', 'type': 'vra_raster'},
            {'name': 'VRA_VECTOR.shp', 'type': 'vra_vector'},
            {'name': 'VRA_STATS.csv', 'type': 'vra_stats'},
        ]
    }
    
    return {
        'job_id': job_id,
        'status': 'ready',
        'download_ready': True,
        'files': files,
        'base_folder': f'{args.drive_folder}/{job_id}',
        'output_dir': args.output_dir or '/tmp',
        'message': f'All files ready for download'
    }

# ============================================================================
# START TASKS
# ============================================================================

def start_tasks(args):
    """Start pending tasks"""
    tasks = ee.batch.Task.list()
    job_tasks = [t for t in tasks if args.job_id in t.config.get('description', '')]
    
    started = 0
    for task in job_tasks:
        if task.state == 'READY':
            task.start()
            started += 1
    
    return {
        'job_id': args.job_id,
        'started': started,
        'message': f'Started {started} pending tasks'
    }

# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_args()
    
    try:
        if args.mode == 'execute':
            result = execute_analysis(args)
        elif args.mode == 'check-status':
            result = check_status(args)
        elif args.mode == 'download-results':
            result = download_results(args)
        elif args.mode == 'start-tasks':
            result = start_tasks(args)
        else:
            result = {'error': f'Unknown mode: {args.mode}'}
        
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        import traceback
        print(json.dumps({
            'error': str(e),
            'traceback': traceback.format_exc()
        }))
        sys.exit(1)

if __name__ == '__main__':
    main()
