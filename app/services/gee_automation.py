#!/usr/bin/env python3
"""
Mu.Orbita GEE Automation Script v3
- Exporta CSV de KPIs a Google Drive
- Calcula todos los índices (NDVI, NDWI, EVI, NDCI)
- Incluye estadísticas completas (mean, P10, P50, P90, stdDev)
- Calcula área de estrés (NDVI < 0.35)
- Añade datos térmicos MODIS LST
"""

import argparse
import json
import ee
import sys
import os
from datetime import datetime, timedelta

# Inicializar Earth Engine con Service Account
def initialize_gee():
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

def parse_args():
    parser = argparse.ArgumentParser(description='Mu.Orbita GEE Automation v3')
    parser.add_argument('--mode', required=True, 
                        choices=['execute', 'check-status', 'download-results', 'start-tasks'])
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--roi', help='GeoJSON string of ROI')
    parser.add_argument('--start-date', help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', help='End date YYYY-MM-DD')
    parser.add_argument('--crop', default='olivar', help='Crop type')
    parser.add_argument('--buffer', type=int, default=0, help='Buffer in meters')
    parser.add_argument('--analysis-type', default='baseline', help='Type of analysis')
    parser.add_argument('--drive-folder', default='MuOrbita_Outputs', help='Google Drive folder')
    parser.add_argument('--output-dir', help='Local output directory')
    return parser.parse_args()

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

def get_sentinel2_collection(roi, start_date, end_date):
    """Get Sentinel-2 SR collection with cloud masking"""
    def mask_clouds(image):
        qa = image.select('QA60')
        scl = image.select('SCL')
        
        # QA60 cloud mask
        cloud_mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
        
        # SCL mask (exclude clouds, shadows, snow)
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
    
    # SAVI (Soil Adjusted Vegetation Index) - good for sparse vegetation like olive groves
    L = 0.5
    savi = nir.subtract(red).divide(nir.add(red).add(L)).multiply(1 + L).rename('SAVI')
    
    return image.addBands([ndvi, ndwi, evi, ndci, savi])

def get_modis_lst(roi, start_date, end_date):
    """Get MODIS Land Surface Temperature"""
    modis = (ee.ImageCollection('MODIS/061/MOD11A2')
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .select('LST_Day_1km')
        .map(lambda img: img.multiply(0.02).subtract(273.15).rename('LST_C')
             .copyProperties(img, ['system:time_start'])))
    
    return modis.median().clip(roi)

def execute_analysis(args):
    """Execute GEE analysis and start export tasks"""
    roi = create_roi(args.roi, args.buffer)
    
    # Get Sentinel-2 collection
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    
    if count == 0:
        return {
            "error": "No images found for the specified date range and ROI",
            "job_id": args.job_id,
            "start_date": args.start_date,
            "end_date": args.end_date
        }
    
    # Calculate indices on all images, then get median composite
    indexed_collection = collection.map(calculate_indices)
    composite = indexed_collection.median().clip(roi)
    
    # Get latest image date
    latest = collection.sort('system:time_start', False).first()
    try:
        latest_date = ee.Date(latest.get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date
    
    # Calculate comprehensive statistics
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI']).reduceRegion(
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
    
    # Calculate historical mean for z-score
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
        lst_mean = lst_min = lst_max = None
    
    # Build comprehensive KPIs
    kpis = {
        'job_id': args.job_id,
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
        
        # SAVI
        'savi_mean': round(stats.get('SAVI_mean', 0) or 0, 3),
        
        # Stress
        'stress_area_ha': round(stress_ha, 2),
        'stress_area_pct': round(stress_pct, 1),
        
        # Thermal (MODIS LST)
        'lst_mean_c': round(lst_mean, 1) if lst_mean else None,
        'lst_min_c': round(lst_min, 1) if lst_min else None,
        'lst_max_c': round(lst_max, 1) if lst_max else None,
        
        # Quality
        'valid_pixels': stats.get('NDVI_count', 0)
    }
    
    # ========== EXPORT TASKS ==========
    tasks = []
    drive_folder = args.drive_folder
    job_id = args.job_id
    
    # 1. Export NDVI map
    task_ndvi = ee.batch.Export.image.toDrive(
        image=composite.select('NDVI'),
        description=f'{job_id}_NDVI',
        folder=drive_folder,
        fileNamePrefix=f'{job_id}_NDVI',
        region=roi,
        scale=10,
        maxPixels=1e9
    )
    task_ndvi.start()
    tasks.append({'name': f'{job_id}_NDVI.tif', 'type': 'ndvi_map', 'id': task_ndvi.id})
    
    # 2. Export NDWI map
    task_ndwi = ee.batch.Export.image.toDrive(
        image=composite.select('NDWI'),
        description=f'{job_id}_NDWI',
        folder=drive_folder,
        fileNamePrefix=f'{job_id}_NDWI',
        region=roi,
        scale=10,
        maxPixels=1e9
    )
    task_ndwi.start()
    tasks.append({'name': f'{job_id}_NDWI.tif', 'type': 'ndwi_map', 'id': task_ndwi.id})
    
    # 3. Export EVI map
    task_evi = ee.batch.Export.image.toDrive(
        image=composite.select('EVI'),
        description=f'{job_id}_EVI',
        folder=drive_folder,
        fileNamePrefix=f'{job_id}_EVI',
        region=roi,
        scale=10,
        maxPixels=1e9
    )
    task_evi.start()
    tasks.append({'name': f'{job_id}_EVI.tif', 'type': 'evi_map', 'id': task_evi.id})
    
    # 4. Export NDCI map
    task_ndci = ee.batch.Export.image.toDrive(
        image=composite.select('NDCI'),
        description=f'{job_id}_NDCI',
        folder=drive_folder,
        fileNamePrefix=f'{job_id}_NDCI',
        region=roi,
        scale=10,
        maxPixels=1e9
    )
    task_ndci.start()
    tasks.append({'name': f'{job_id}_NDCI.tif', 'type': 'ndci_map', 'id': task_ndci.id})
    
    # 5. Export KPIs as CSV to Drive
    kpi_feature = ee.Feature(None, kpis)
    kpi_collection = ee.FeatureCollection([kpi_feature])
    
    task_kpis = ee.batch.Export.table.toDrive(
        collection=kpi_collection,
        description=f'{job_id}_KPIs',
        folder=drive_folder,
        fileNamePrefix=f'{job_id}_KPIs',
        fileFormat='CSV'
    )
    task_kpis.start()
    tasks.append({'name': f'{job_id}_KPIs.csv', 'type': 'kpis', 'id': task_kpis.id})
    
    # 6. Export time series
    ts_features = indexed_collection.select(['NDVI', 'NDWI', 'EVI']).map(lambda img: 
        ee.Feature(None, img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=roi,
            scale=20,
            maxPixels=1e9
        )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
    )
    
    task_ts = ee.batch.Export.table.toDrive(
        collection=ee.FeatureCollection(ts_features),
        description=f'{job_id}_TimeSeries',
        folder=drive_folder,
        fileNamePrefix=f'{job_id}_TimeSeries',
        fileFormat='CSV'
    )
    task_ts.start()
    tasks.append({'name': f'{job_id}_TimeSeries.csv', 'type': 'timeseries', 'id': task_ts.id})
    
    # Return result with KPIs included
    result = {
        'success': True,
        'job_id': args.job_id,
        'kpis': kpis,
        'tasks': tasks,
        'task_count': len(tasks),
        'drive_folder': drive_folder,
        'message': f'Analysis complete. {len(tasks)} export tasks started.'
    }
    
    return result

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
    
    return {
        'job_id': args.job_id,
        'tasks': status,
        'completed': completed,
        'running': running,
        'failed': failed,
        'pending': pending,
        'total': total,
        'all_complete': all_complete,
        'any_failed': failed > 0,
        'progress_pct': round(completed / total * 100) if total > 0 else 0,
        'message': f'COMPLETED: {completed}, RUNNING: {running}, FAILED: {failed}, PENDING: {pending}'
    }

def download_results(args):
    """Return info about exported files for n8n to download"""
    status = check_status(args)
    
    if not status['all_complete']:
        return {
            'job_id': args.job_id,
            'status': 'waiting',
            'download_ready': False,
            'message': 'Tasks not yet complete',
            'progress': status
        }
    
    # Create output directory if specified
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
    
    # List of files to download
    job_id = args.job_id
    files = [
        {'name': f'{job_id}_NDVI.tif', 'type': 'ndvi_map'},
        {'name': f'{job_id}_NDWI.tif', 'type': 'ndwi_map'},
        {'name': f'{job_id}_EVI.tif', 'type': 'evi_map'},
        {'name': f'{job_id}_NDCI.tif', 'type': 'ndci_map'},
        {'name': f'{job_id}_KPIs.csv', 'type': 'kpis'},
        {'name': f'{job_id}_TimeSeries.csv', 'type': 'timeseries'}
    ]
    
    return {
        'job_id': args.job_id,
        'status': 'ready',
        'download_ready': True,
        'files': files,
        'drive_folder': args.drive_folder,
        'output_dir': args.output_dir or '/tmp',
        'message': f'{len(files)} files ready for download'
    }

def start_tasks(args):
    """Start pending tasks (if any were created but not started)"""
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