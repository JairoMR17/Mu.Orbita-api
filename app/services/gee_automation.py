#!/usr/bin/env python3
"""
Mu.Orbita GEE Automation Script v5.0 (NO-DRIVE)
=================================================

CAMBIOS V5.0 vs V4.1:
✅ Eliminado Export.image.toDrive() — ya no necesita Google Drive
✅ PNGs generados con getThumbURL() — descarga directa e inmediata
✅ Imágenes devueltas como base64 en el JSON — listas para BD/dashboard/PDF
✅ CSVs eliminados de Drive — datos ya están en el JSON de respuesta
✅ Ejecución 10x más rápida (2-5 min vs 20-40 min)
✅ Sin tareas asíncronas — todo se resuelve en una sola llamada
✅ Compatible con el router gee.py existente (misma interfaz)

MODOS:
    baseline:   Análisis completo (todos los índices + VRA + imágenes PNG)
    biweekly:   Seguimiento ligero (NDVI + NDWI + weather ERA5)
"""

import argparse
import json
import ee
import sys
import os
import base64
import urllib.request
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
# PALETAS DE VISUALIZACIÓN
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
        'palette': ['e74c3c', 'f1c40f', '27ae60']
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
    parser = argparse.ArgumentParser(description='Mu.Orbita GEE Automation v5.0 (No-Drive)')
    parser.add_argument('--mode', required=True, 
                        choices=['execute', 'check-status', 'download-results', 'start-tasks'])
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--roi', help='GeoJSON string of ROI')
    parser.add_argument('--start-date', help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', help='End date YYYY-MM-DD')
    parser.add_argument('--crop', default='olivar', help='Crop type')
    parser.add_argument('--buffer', type=int, default=0, help='Buffer in meters')
    parser.add_argument('--analysis-type', default='baseline', help='Type of analysis: baseline or biweekly')
    parser.add_argument('--drive-folder', default='MuOrbita_Outputs', help='(legacy, unused)')
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


def get_png_base64(image, roi, viz_params, dimensions=1024):
    """
    Genera un PNG coloreado directamente desde GEE y lo devuelve como base64.
    
    SIN exportar a Drive. Usa getThumbURL() para obtener una URL temporal,
    descarga los bytes y los codifica en base64.
    
    Args:
        image: ee.Image con la banda a visualizar
        roi: ee.Geometry del área
        viz_params: dict con min, max, palette
        dimensions: resolución máxima del PNG (px del lado más largo)
    
    Returns:
        str: PNG codificado en base64, o None si falla
    """
    try:
        # Generar URL temporal del PNG coloreado
        url = image.visualize(**viz_params).getThumbURL({
            'region': roi,
            'dimensions': dimensions,
            'format': 'png'
        })
        
        # Descargar PNG inmediatamente
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.0')
        response = urllib.request.urlopen(req, timeout=60)
        png_bytes = response.read()
        
        # Verificar que recibimos datos válidos
        if len(png_bytes) < 100:
            print(f"Warning: PNG too small ({len(png_bytes)} bytes), might be an error")
            return None
        
        # Codificar en base64
        return base64.b64encode(png_bytes).decode('utf-8')
        
    except Exception as e:
        print(f"Warning: Could not generate PNG: {e}")
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
    
    L = 0.5
    savi = nir.subtract(red).divide(nir.add(red).add(L)).multiply(1 + L).rename('SAVI')
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
        training_bands = ['NDVI', 'EVI', 'NDWI']
        training_image = composite.select(training_bands)
        
        valid_mask = training_image.mask().reduce(ee.Reducer.min())
        training_masked = training_image.updateMask(valid_mask)
        
        sample = training_masked.sample(
            region=roi,
            scale=20,
            numPixels=5000,
            geometries=False
        )
        
        clusterer = ee.Clusterer.wekaKMeans(3).train(sample)
        vra = training_masked.cluster(clusterer).rename('zone')
        
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
# ERA5 WEATHER DATA
# ============================================================================

def get_era5_weather(roi, start_date, end_date):
    """
    Obtiene datos meteorológicos de ERA5-Land para el período.
    """
    weather_kpis = {}
    daily_series = []
    
    tmax_by_date = {}
    tmin_by_date = {}
    precip_by_date = {}
    et_by_date = {}
    
    try:
        # ---- TEMPERATURA ----
        era5_tmax = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('temperature_2m_max')
            .map(lambda img: img.subtract(273.15).rename('Tmax_C')
                 .copyProperties(img, ['system:time_start'])))
        
        era5_tmin = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('temperature_2m_min')
            .map(lambda img: img.subtract(273.15).rename('Tmin_C')
                 .copyProperties(img, ['system:time_start'])))
        
        tmax_values = era5_tmax.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'tmax': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('Tmax_C')
        }))
        
        tmin_values = era5_tmin.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'tmin': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('Tmin_C')
        }))
        
        tmax_list = tmax_values.toList(100).getInfo()
        tmin_list = tmin_values.toList(100).getInfo()
        
        tmax_vals = []
        tmin_vals = []
        heat_days = 0
        frost_days = 0
        gdd_total = 0
        
        for f in tmax_list:
            props = f.get('properties', {})
            val = props.get('tmax')
            date = props.get('date', '')
            if val is not None:
                tmax_vals.append(val)
                tmax_by_date[date] = val
                if val >= 35:
                    heat_days += 1
        
        for f in tmin_list:
            props = f.get('properties', {})
            val = props.get('tmin')
            date = props.get('date', '')
            if val is not None:
                tmin_vals.append(val)
                tmin_by_date[date] = val
                if val <= 0:
                    frost_days += 1
        
        for date in tmax_by_date:
            tmax_d = tmax_by_date.get(date)
            tmin_d = tmin_by_date.get(date)
            if tmax_d is not None and tmin_d is not None:
                tmean = (tmax_d + tmin_d) / 2
                gdd_total += max(0, tmean - 10)
        
        weather_kpis['weather_tmax_mean'] = round(sum(tmax_vals) / len(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmax_max'] = round(max(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmin_mean'] = round(sum(tmin_vals) / len(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_tmin_min'] = round(min(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_heat_days'] = heat_days
        weather_kpis['weather_frost_days'] = frost_days
        weather_kpis['weather_gdd_base10'] = round(gdd_total, 1)
        
    except Exception as e:
        print(f"Warning: ERA5 temperature failed: {e}")
        weather_kpis['weather_tmax_mean'] = None
        weather_kpis['weather_tmin_mean'] = None
        weather_kpis['weather_heat_days'] = None
        weather_kpis['weather_frost_days'] = None
        weather_kpis['weather_gdd_base10'] = None
    
    try:
        # ---- PRECIPITACIÓN ----
        era5_precip = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('total_precipitation_sum')
            .map(lambda img: img.multiply(1000).rename('Precip_mm')
                 .copyProperties(img, ['system:time_start'])))
        
        precip_values = era5_precip.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'precip': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('Precip_mm')
        }))
        
        precip_list = precip_values.toList(100).getInfo()
        precip_vals = []
        rain_days = 0
        
        for f in precip_list:
            props = f.get('properties', {})
            val = props.get('precip')
            date = props.get('date', '')
            if val is not None:
                precip_vals.append(val)
                precip_by_date[date] = val
                if val > 1:
                    rain_days += 1
        
        weather_kpis['weather_precip_total_mm'] = round(sum(precip_vals), 1) if precip_vals else None
        weather_kpis['weather_precip_max_daily_mm'] = round(max(precip_vals), 1) if precip_vals else None
        weather_kpis['weather_rain_days'] = rain_days
        
    except Exception as e:
        print(f"Warning: ERA5 precipitation failed: {e}")
        weather_kpis['weather_precip_total_mm'] = None
        weather_kpis['weather_rain_days'] = None
    
    try:
        # ---- EVAPOTRANSPIRACIÓN ----
        era5_et = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('total_evaporation_sum')
            .map(lambda img: img.multiply(-1000).rename('ET_mm')
                 .copyProperties(img, ['system:time_start'])))
        
        et_values = era5_et.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'et': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('ET_mm')
        }))
        
        et_list = et_values.toList(100).getInfo()
        et_vals = []
        for f in et_list:
            props = f.get('properties', {})
            val = props.get('et')
            date = props.get('date', '')
            if val is not None:
                et_vals.append(val)
                et_by_date[date] = val
        
        et_total = sum(et_vals) if et_vals else 0
        precip_total = weather_kpis.get('weather_precip_total_mm') or 0
        
        weather_kpis['weather_et_total_mm'] = round(et_total, 1) if et_vals else None
        weather_kpis['weather_water_balance_mm'] = round(precip_total - et_total, 1)
        
    except Exception as e:
        print(f"Warning: ERA5 ET failed: {e}")
        weather_kpis['weather_et_total_mm'] = None
        weather_kpis['weather_water_balance_mm'] = None
    
    try:
        # ---- VIENTO ----
        era5_wind_u = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('u_component_of_wind_10m'))
        
        era5_wind_v = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('v_component_of_wind_10m'))
        
        wind_speed_mean = era5_wind_u.mean().pow(2).add(era5_wind_v.mean().pow(2)).sqrt()
        wind_stats = wind_speed_mean.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
        ).getInfo()
        
        wind_val = list(wind_stats.values())[0] if wind_stats else None
        weather_kpis['weather_wind_mean_ms'] = round(wind_val, 1) if wind_val else None
        
    except Exception as e:
        print(f"Warning: ERA5 wind failed: {e}")
        weather_kpis['weather_wind_mean_ms'] = None
    
    try:
        # ---- HUMEDAD DEL SUELO ----
        era5_sm = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('volumetric_soil_water_layer_1'))
        
        sm_stats = era5_sm.reduce(
            ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
        ).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
        ).getInfo()
        
        weather_kpis['weather_soil_moisture_mean'] = round(
            sm_stats.get('volumetric_soil_water_layer_1_mean', 0) or 0, 3)
        weather_kpis['weather_soil_moisture_min'] = round(
            sm_stats.get('volumetric_soil_water_layer_1_min', 0) or 0, 3)
        
    except Exception as e:
        print(f"Warning: ERA5 soil moisture failed: {e}")
        weather_kpis['weather_soil_moisture_mean'] = None
    
    # ---- SERIE TEMPORAL DIARIA ----
    all_dates = sorted(set(
        list(tmax_by_date.keys()) + list(tmin_by_date.keys()) + 
        list(precip_by_date.keys()) + list(et_by_date.keys())
    ))
    
    for date in all_dates:
        daily_series.append({
            'date': date,
            'tmax_c': round(tmax_by_date.get(date, -9999), 1),
            'tmin_c': round(tmin_by_date.get(date, -9999), 1),
            'precip_mm': round(precip_by_date.get(date, 0), 1),
            'et_mm': round(et_by_date.get(date, 0), 1),
        })
    
    return weather_kpis, daily_series


# ============================================================================
# EJECUTAR ANÁLISIS BIWEEKLY
# ============================================================================

def execute_biweekly_analysis(args):
    """
    Análisis BIWEEKLY ligero — SIN Drive, PNGs directos.
    """
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)
    
    # ========== DATOS SATELITALES ==========
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    
    if count == 0:
        return {
            "error": "No images found for the biweekly period",
            "job_id": job_id,
            "analysis_type": "biweekly",
            "start_date": args.start_date,
            "end_date": args.end_date,
            "suggestion": "Try extending the date range or check cloud cover"
        }
    
    indexed_collection = collection.map(calculate_indices)
    composite = indexed_collection.median().clip(roi)
    
    latest = collection.sort('system:time_start', False).first()
    try:
        latest_date = ee.Date(latest.get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date
    
    # ========== ESTADÍSTICAS ==========
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    
    area_ha = roi.area().divide(10000).getInfo()
    
    stress_mask = composite.select('NDVI').lt(0.35)
    stress_area = stress_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    stress_ha = stress_area.get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0
    
    hist_stats = indexed_collection.select('NDVI').mean().reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=20, maxPixels=1e9
    ).getInfo()
    
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0
    
    # ========== ERA5 WEATHER ==========
    weather_kpis, weather_daily = get_era5_weather(roi, args.start_date, args.end_date)
    
    # ========== MODIS LST ==========
    try:
        lst = get_modis_lst(roi, args.start_date, args.end_date)
        lst_stats = lst.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, scale=1000, maxPixels=1e9
        ).getInfo()
        lst_mean = lst_stats.get('LST_C_mean', None)
    except:
        lst_mean = None
    
    # ========== SERIE TEMPORAL ==========
    time_series = []
    try:
        ts_features = indexed_collection.select(['NDVI', 'NDWI', 'EVI']).map(lambda img: 
            ee.Feature(None, img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
        )
        ts_list = ts_features.toList(100).getInfo()
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
    
    # ========== GENERAR PNGs DIRECTAMENTE (SIN DRIVE) ==========
    print("Generating PNG images directly from GEE...")
    
    images_base64 = {}
    for idx_name in ['NDVI', 'NDWI']:
        print(f"  Generating {idx_name} PNG...")
        b64 = get_png_base64(
            composite.select(idx_name), 
            roi, 
            VIZ_PALETTES[idx_name],
            dimensions=1024
        )
        if b64:
            images_base64[idx_name] = b64
            print(f"  ✓ {idx_name}: {len(b64)} chars base64")
        else:
            print(f"  ✗ {idx_name}: failed")
    
    # ========== KPIs ==========
    kpis = {
        'job_id': job_id,
        'crop_type': args.crop,
        'analysis_type': 'biweekly',
        'start_date': args.start_date,
        'end_date': args.end_date,
        'latest_image_date': latest_date,
        'images_processed': count,
        'area_hectares': round(area_ha, 2),
        'ndvi_mean': round(stats.get('NDVI_mean', 0) or 0, 3),
        'ndvi_p10': round(stats.get('NDVI_p10', 0) or 0, 3),
        'ndvi_p50': round(stats.get('NDVI_p50', 0) or 0, 3),
        'ndvi_p90': round(stats.get('NDVI_p90', 0) or 0, 3),
        'ndvi_stddev': round(stats.get('NDVI_stdDev', 0) or 0, 3),
        'ndvi_zscore': round(z_score, 2),
        'ndwi_mean': round(stats.get('NDWI_mean', 0) or 0, 3),
        'ndwi_p10': round(stats.get('NDWI_p10', 0) or 0, 3),
        'ndwi_p90': round(stats.get('NDWI_p90', 0) or 0, 3),
        'evi_mean': round(stats.get('EVI_mean', 0) or 0, 3),
        'ndci_mean': round(stats.get('NDCI_mean', 0) or 0, 3),
        'stress_area_ha': round(stress_ha, 2),
        'stress_area_pct': round(stress_pct, 1),
        'lst_mean_c': round(lst_mean, 1) if lst_mean else None,
        'bounds_south': bounds['south'] if bounds else None,
        'bounds_west': bounds['west'] if bounds else None,
        'bounds_north': bounds['north'] if bounds else None,
        'bounds_east': bounds['east'] if bounds else None,
    }
    kpis.update(weather_kpis)
    
    # ========== RESULTADO ==========
    result = {
        'success': True,
        'job_id': job_id,
        'analysis_type': 'biweekly',
        'kpis': kpis,
        'weather': weather_kpis,
        'weather_daily': weather_daily,
        'bounds': bounds,
        'time_series': time_series,
        'images_base64': images_base64,
        'tasks': [],
        'task_count': 0,
        'message': f'Biweekly analysis complete. {len(images_base64)} PNG images generated directly. No Drive exports needed.'
    }
    
    return result


# ============================================================================
# EJECUTAR ANÁLISIS BASELINE
# ============================================================================

def execute_analysis(args):
    """
    Análisis BASELINE completo — SIN Drive, PNGs directos.
    """
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)
    
    # ========== DATOS SATELITALES ==========
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    
    if count == 0:
        return {
            "error": "No images found for the specified date range and ROI",
            "job_id": job_id,
            "start_date": args.start_date,
            "end_date": args.end_date
        }
    
    indexed_collection = collection.map(calculate_indices)
    composite = indexed_collection.median().clip(roi)
    
    latest = collection.sort('system:time_start', False).first()
    try:
        latest_date = ee.Date(latest.get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date
    
    # ========== ESTADÍSTICAS ==========
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI', 'OSAVI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    
    area_ha = roi.area().divide(10000).getInfo()
    
    stress_mask = composite.select('NDVI').lt(0.35)
    stress_area = stress_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    stress_ha = stress_area.get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0
    
    hist_stats = indexed_collection.select('NDVI').mean().reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=20, maxPixels=1e9
    ).getInfo()
    
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0
    
    # ========== MODIS LST ==========
    try:
        lst = get_modis_lst(roi, args.start_date, args.end_date)
        lst_stats = lst.reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True),
            geometry=roi, scale=1000, maxPixels=1e9
        ).getInfo()
        lst_mean = lst_stats.get('LST_C_mean', None)
        lst_min = lst_stats.get('LST_C_min', None)
        lst_max = lst_stats.get('LST_C_max', None)
    except:
        lst = None
        lst_mean = lst_min = lst_max = None
    
    # ========== VRA ==========
    vra_image, vra_stats = calculate_vra_zones(composite, roi)
    
    # ========== KPIs ==========
    kpis = {
        'job_id': job_id,
        'crop_type': args.crop,
        'analysis_type': args.analysis_type,
        'start_date': args.start_date,
        'end_date': args.end_date,
        'latest_image_date': latest_date,
        'images_processed': count,
        'area_hectares': round(area_ha, 2),
        'ndvi_mean': round(stats.get('NDVI_mean', 0) or 0, 3),
        'ndvi_p10': round(stats.get('NDVI_p10', 0) or 0, 3),
        'ndvi_p50': round(stats.get('NDVI_p50', 0) or 0, 3),
        'ndvi_p90': round(stats.get('NDVI_p90', 0) or 0, 3),
        'ndvi_stddev': round(stats.get('NDVI_stdDev', 0) or 0, 3),
        'ndvi_zscore': round(z_score, 2),
        'ndwi_mean': round(stats.get('NDWI_mean', 0) or 0, 3),
        'ndwi_p10': round(stats.get('NDWI_p10', 0) or 0, 3),
        'ndwi_p90': round(stats.get('NDWI_p90', 0) or 0, 3),
        'evi_mean': round(stats.get('EVI_mean', 0) or 0, 3),
        'evi_p10': round(stats.get('EVI_p10', 0) or 0, 3),
        'evi_p90': round(stats.get('EVI_p90', 0) or 0, 3),
        'ndci_mean': round(stats.get('NDCI_mean', 0) or 0, 3),
        'savi_mean': round(stats.get('SAVI_mean', 0) or 0, 3),
        'osavi_mean': round(stats.get('OSAVI_mean', 0) or 0, 3),
        'stress_area_ha': round(stress_ha, 2),
        'stress_area_pct': round(stress_pct, 1),
        'lst_mean_c': round(lst_mean, 1) if lst_mean else None,
        'lst_min_c': round(lst_min, 1) if lst_min else None,
        'lst_max_c': round(lst_max, 1) if lst_max else None,
        'bounds_south': bounds['south'] if bounds else None,
        'bounds_west': bounds['west'] if bounds else None,
        'bounds_north': bounds['north'] if bounds else None,
        'bounds_east': bounds['east'] if bounds else None,
        'valid_pixels': stats.get('NDVI_count', 0)
    }
    
    # ========== GENERAR PNGs DIRECTAMENTE (SIN DRIVE) ==========
    print("Generating PNG images directly from GEE...")
    
    images_base64 = {}
    
    # Índices vegetativos
    for idx_name in ['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI']:
        print(f"  Generating {idx_name} PNG...")
        b64 = get_png_base64(
            composite.select(idx_name), 
            roi, 
            VIZ_PALETTES[idx_name],
            dimensions=1024
        )
        if b64:
            images_base64[idx_name] = b64
            print(f"  ✓ {idx_name}: {len(b64)} chars base64")
        else:
            print(f"  ✗ {idx_name}: failed")
    
    # VRA
    if vra_image is not None:
        print("  Generating VRA PNG...")
        b64 = get_png_base64(
            vra_image, 
            roi, 
            VIZ_PALETTES['VRA'],
            dimensions=1024
        )
        if b64:
            images_base64['VRA'] = b64
            print(f"  ✓ VRA: {len(b64)} chars base64")
    
    # LST
    if lst is not None:
        print("  Generating LST PNG...")
        b64 = get_png_base64(
            lst, 
            roi, 
            VIZ_PALETTES['LST'],
            dimensions=512
        )
        if b64:
            images_base64['LST'] = b64
            print(f"  ✓ LST: {len(b64)} chars base64")
    
    # ========== SERIE TEMPORAL ==========
    time_series = []
    try:
        ts_features = indexed_collection.select(['NDVI', 'NDWI', 'EVI']).map(lambda img: 
            ee.Feature(None, img.reduceRegion(
                reducer=ee.Reducer.mean()
                    .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True),
                geometry=roi, scale=20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
        )
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
    
    # ========== RESULTADO ==========
    result = {
        'success': True,
        'job_id': job_id,
        'analysis_type': 'baseline',
        'kpis': kpis,
        'vra_stats': vra_stats,
        'bounds': bounds,
        'images_base64': images_base64,
        'time_series': time_series,
        'tasks': [],
        'task_count': 0,
        'message': f'Baseline analysis complete. {len(images_base64)} PNG images generated directly. No Drive exports needed.'
    }
    
    return result

# ============================================================================
# CHECK STATUS (legacy — ahora siempre "complete" porque no hay tasks)
# ============================================================================

def check_status(args):
    """Check status — con v5.0 siempre está completo (no hay tasks asíncronos)"""
    return {
        'job_id': args.job_id,
        'tasks': [],
        'completed': 0,
        'running': 0,
        'failed': 0,
        'pending': 0,
        'total': 0,
        'all_complete': True,
        'png_complete': True,
        'any_failed': False,
        'progress_pct': 100,
        'message': 'v5.0: No async tasks. All data returned immediately in execute response.'
    }

# ============================================================================
# DOWNLOAD RESULTS (legacy — datos ya están en el JSON de execute)
# ============================================================================

def download_results(args):
    """Download results — con v5.0 no aplica, datos ya en JSON"""
    return {
        'job_id': args.job_id,
        'analysis_type': getattr(args, 'analysis_type', 'baseline'),
        'status': 'ready',
        'download_ready': True,
        'message': 'v5.0: All data (KPIs, images, time series) returned directly in the execute response. No Drive downloads needed.'
    }

# ============================================================================
# START TASKS (legacy — no hay tasks)
# ============================================================================

def start_tasks(args):
    """Start tasks — con v5.0 no aplica"""
    return {
        'job_id': args.job_id,
        'started': 0,
        'message': 'v5.0: No async tasks to start. All processing is synchronous.'
    }

# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_args()
    
    try:
        if args.mode == 'execute':
            analysis_type = getattr(args, 'analysis_type', 'baseline')
            if analysis_type == 'biweekly':
                result = execute_biweekly_analysis(args)
            else:
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
