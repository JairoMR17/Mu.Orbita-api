"""
MU.ORBITA - GEE Script Generator v3.2
=====================================
Genera scripts de Google Earth Engine con coordenadas dinámicas
y contexto fenológico para cada cliente.

Uso:
    from gee_script_generator import generate_gee_script
    
    script = generate_gee_script(
        job_id="MUORBITA_123456",
        roi_geojson={"type": "Polygon", "coordinates": [...]},
        crop_type="olivo",
        start_date="2025-01-01",
        end_date="2025-12-15"
    )
"""

import json
from datetime import datetime
from typing import Optional, Union, List


def generate_gee_script(
    job_id: str,
    roi_geojson: Union[dict, str],
    crop_type: str,
    start_date: str,
    end_date: str,
    output_folder_base: str = "MuOrbita_Output"
) -> str:
    """
    Genera script GEE v3.2 con coordenadas dinámicas y curvas fenológicas.
    
    Args:
        job_id: ID único del trabajo (ej: "MUORBITA_1234567890_ABCD")
        roi_geojson: GeoJSON con la geometría del cliente (dict o string JSON)
        crop_type: Tipo de cultivo (olivo, viña, almendro, otro)
        start_date: Fecha inicio análisis (YYYY-MM-DD)
        end_date: Fecha fin análisis (YYYY-MM-DD)
        output_folder_base: Carpeta base en Google Drive
    
    Returns:
        Script GEE completo como string, listo para ejecutar
    
    Example:
        >>> script = generate_gee_script(
        ...     job_id="TEST_001",
        ...     roi_geojson={"type": "Polygon", "coordinates": [[[-6.19, 36.66], [-6.17, 36.65], [-6.19, 36.66]]]},
        ...     crop_type="olivo",
        ...     start_date="2025-01-01",
        ...     end_date="2025-12-15"
        ... )
        >>> print(script[:100])
        /*******************************************************************************
         * MU.ORBITA — GEE SCRIPT V3.2 (PHENOLOGICAL CONTEXT)
    """
    
    # Parsear GeoJSON si viene como string
    if isinstance(roi_geojson, str):
        roi_geojson = json.loads(roi_geojson)
    
    # Mapear tipo de cultivo a formato GEE
    crop_type_map = {
        'olivo': 'olivo',
        'olivar': 'olivo',
        'oliva': 'olivo',
        'viña': 'vina',
        'viñedo': 'vina',
        'vid': 'vina',
        'vino': 'vina',
        'almendro': 'almendro',
        'almendra': 'almendro',
        'almendral': 'almendro'
    }
    gee_crop_type = crop_type_map.get(crop_type.lower().strip(), 'otro')
    
    # Extraer coordenadas del GeoJSON
    coords = extract_coordinates(roi_geojson)
    if not coords:
        raise ValueError(f"No se pudieron extraer coordenadas del GeoJSON: {roi_geojson}")
    
    coords_js = json.dumps(coords, indent=2)
    
    # Carpetas de salida organizadas por job
    out_folder_indices = f"{output_folder_base}/{job_id}/indices"
    out_folder_grafics = f"{output_folder_base}/{job_id}/graficos"
    out_folder_prescr = f"{output_folder_base}/{job_id}/prescripcion"
    
    # Generar timestamp
    generated_at = datetime.now().isoformat()
    
    # Construir script completo
    script = f'''/*******************************************************************************
 * MU.ORBITA — GEE SCRIPT V3.2 (PHENOLOGICAL CONTEXT)
 * Generated: {generated_at}
 * Job ID: {job_id}
 * Crop Type: {gee_crop_type}
 * 
 * FEATURES:
 * ✅ Dynamic ROI from client GeoJSON
 * ✅ Phenological curves for olivo, viña, almendro
 * ✅ Seasonal z-score (same period comparison)
 * ✅ Expected NDVI based on crop and DOY
 * ✅ Phenological status indicator
 ******************************************************************************/

// ===================== CONFIGURATION (AUTO-GENERATED) ======================

var START_DATE = '{start_date}';
var END_DATE = '{end_date}';
var CROP_TYPE = '{gee_crop_type}';
var JOB_ID = '{job_id}';

// ROI from client's GeoJSON (auto-extracted)
var coords = {coords_js};
var roi = ee.Geometry.Polygon(coords);

// Output folders (organized by job)
var OUT_FOLDER_INDICES = '{out_folder_indices}';
var OUT_FOLDER_GRAFICS = '{out_folder_grafics}';
var OUT_FOLDER_PRESCR = '{out_folder_prescr}';

Map.centerObject(roi, 14);
Map.addLayer(roi, {{color: 'FF0000'}}, '0. ROI', true, 0.3);

print('🚀 Mu.Orbita GEE Analysis v3.2 (Phenological Context)');
print('📅 Period:', START_DATE, 'to', END_DATE);
print('🌱 Crop type:', CROP_TYPE);
print('🔑 JOB_ID:', JOB_ID);

{PHENOLOGICAL_FUNCTIONS}

{DATA_ACQUISITION}

{VEGETATION_INDICES}

{VISUALIZATION}

{GEOTIFF_EXPORTS}

{TIME_SERIES}

{KPIS_WITH_PHENOLOGY}

{VRA_ZONING}

{THERMAL_ANALYSIS}

{SUMMARY}
'''
    
    return script


def extract_coordinates(geojson: Union[dict, str, None]) -> List[List[float]]:
    """
    Extrae coordenadas de un GeoJSON en varios formatos.
    
    Soporta:
    - Polygon
    - MultiPolygon (toma el primer polígono)
    - Feature
    - FeatureCollection (toma la primera feature)
    
    Args:
        geojson: Objeto GeoJSON (dict o string JSON)
    
    Returns:
        Lista de coordenadas [[lon, lat], [lon, lat], ...]
    
    Raises:
        ValueError: Si no se pueden extraer coordenadas
    """
    if geojson is None:
        return []
    
    # Parsear si es string
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except json.JSONDecodeError:
            return []
    
    if not isinstance(geojson, dict):
        return []
    
    geo_type = geojson.get('type', '')
    
    # FeatureCollection -> primera Feature
    if geo_type == 'FeatureCollection':
        features = geojson.get('features', [])
        if features:
            return extract_coordinates(features[0])
        return []
    
    # Feature -> su geometry
    if geo_type == 'Feature':
        geometry = geojson.get('geometry')
        if geometry:
            return extract_coordinates(geometry)
        return []
    
    # Polygon -> primer anillo (exterior)
    if geo_type == 'Polygon':
        coordinates = geojson.get('coordinates', [])
        if coordinates and len(coordinates) > 0:
            return coordinates[0]
        return []
    
    # MultiPolygon -> primer polígono, primer anillo
    if geo_type == 'MultiPolygon':
        coordinates = geojson.get('coordinates', [])
        if coordinates and len(coordinates) > 0 and len(coordinates[0]) > 0:
            return coordinates[0][0]
        return []
    
    # Geometría directa sin type (legacy support)
    if 'coordinates' in geojson:
        coordinates = geojson['coordinates']
        if coordinates and len(coordinates) > 0:
            # Detectar si es Polygon o MultiPolygon por profundidad
            if isinstance(coordinates[0], list) and isinstance(coordinates[0][0], list):
                if isinstance(coordinates[0][0][0], list):
                    # MultiPolygon
                    return coordinates[0][0]
                else:
                    # Polygon
                    return coordinates[0]
            return coordinates
    
    return []


# ============================================================================
# BLOQUES DEL SCRIPT GEE
# ============================================================================

PHENOLOGICAL_FUNCTIONS = '''
// ===================== PHENOLOGICAL CURVES ======================
// NDVI expected values by DOY for Mediterranean crops (Andalucía)

/**
 * OLIVE (Olea europaea) - Phenological NDVI curve
 * Stages: Dormancy -> Spring flush -> Flowering -> Fruit dev -> Harvest
 */
function getExpectedNDVI_Olivo(doy) {
  return ee.Number(ee.Algorithms.If(
    doy.lt(32),   // January: Deep dormancy
    0.28,
    ee.Algorithms.If(
      doy.lt(60),   // February: Early recovery
      0.32,
      ee.Algorithms.If(
        doy.lt(91),   // March: Spring flush
        0.42,
        ee.Algorithms.If(
          doy.lt(121),  // April: Active growth
          0.52,
          ee.Algorithms.If(
            doy.lt(152),  // May: Flowering
            0.58,
            ee.Algorithms.If(
              doy.lt(182),  // June: PEAK - Fruit set
              0.62,
              ee.Algorithms.If(
                doy.lt(213),  // July: Fruit development
                0.55,
                ee.Algorithms.If(
                  doy.lt(244),  // August: Summer stress
                  0.48,
                  ee.Algorithms.If(
                    doy.lt(274),  // September: Recovery
                    0.45,
                    ee.Algorithms.If(
                      doy.lt(305),  // October: Pre-harvest
                      0.40,
                      ee.Algorithms.If(
                        doy.lt(335),  // November: Harvest
                        0.35,
                        0.28  // December: Post-harvest
                      ))))))))))));
}

/**
 * VINEYARD (Vitis vinifera) - Phenological NDVI curve
 * Stages: Dormancy -> Bud break -> Peak canopy -> Veraison -> Harvest
 */
function getExpectedNDVI_Vina(doy) {
  return ee.Number(ee.Algorithms.If(
    doy.lt(60),   // Jan-Feb: Deep dormancy
    0.18,
    ee.Algorithms.If(
      doy.lt(91),   // March: Late dormancy
      0.22,
      ee.Algorithms.If(
        doy.lt(121),  // April: Bud break
        0.35,
        ee.Algorithms.If(
          doy.lt(152),  // May: Rapid growth
          0.50,
          ee.Algorithms.If(
            doy.lt(182),  // June: PEAK canopy
            0.58,
            ee.Algorithms.If(
              doy.lt(213),  // July: Veraison
              0.52,
              ee.Algorithms.If(
                doy.lt(244),  // August: Ripening
                0.45,
                ee.Algorithms.If(
                  doy.lt(274),  // September: Late ripening
                  0.40,
                  ee.Algorithms.If(
                    doy.lt(305),  // October: Harvest
                    0.32,
                    ee.Algorithms.If(
                      doy.lt(335),  // November: Senescence
                      0.22,
                      0.18  // December: Dormancy
                    )))))))))));
}

/**
 * ALMOND (Prunus dulcis) - Phenological NDVI curve
 * Stages: Dormancy -> Early flowering -> Full canopy -> Kernel fill -> Harvest
 */
function getExpectedNDVI_Almendro(doy) {
  return ee.Number(ee.Algorithms.If(
    doy.lt(32),   // January: Dormancy
    0.25,
    ee.Algorithms.If(
      doy.lt(60),   // February: FLOWERING (low - no leaves)
      0.22,
      ee.Algorithms.If(
        doy.lt(91),   // March: Leaf emergence
        0.38,
        ee.Algorithms.If(
          doy.lt(121),  // April: Canopy development
          0.52,
          ee.Algorithms.If(
            doy.lt(152),  // May: Full canopy
            0.62,
            ee.Algorithms.If(
              doy.lt(182),  // June: PEAK - Kernel development
              0.65,
              ee.Algorithms.If(
                doy.lt(213),  // July: Kernel filling
                0.58,
                ee.Algorithms.If(
                  doy.lt(244),  // August: Pre-harvest
                  0.50,
                  ee.Algorithms.If(
                    doy.lt(274),  // September: Harvest
                    0.42,
                    ee.Algorithms.If(
                      doy.lt(305),  // October: Post-harvest
                      0.35,
                      ee.Algorithms.If(
                        doy.lt(335),  // November: Senescence
                        0.28,
                        0.25  // December: Dormancy
                      ))))))))))));
}

/**
 * Returns expected NDVI based on crop type and DOY
 * For unknown crops ('otro'), returns null
 */
function getExpectedNDVI(cropType, doy) {
  return ee.Algorithms.If(
    ee.String(cropType).equals('olivo'),
    getExpectedNDVI_Olivo(doy),
    ee.Algorithms.If(
      ee.String(cropType).equals('vina'),
      getExpectedNDVI_Vina(doy),
      ee.Algorithms.If(
        ee.String(cropType).equals('almendro'),
        getExpectedNDVI_Almendro(doy),
        null  // 'otro' - no expected value
      )
    )
  );
}

/**
 * Returns phenological phase name for the crop
 */
function getPhenologicalPhase(cropType, doy) {
  var olivoPhases = ee.Algorithms.If(
    doy.lt(60), 'Latencia invernal',
    ee.Algorithms.If(doy.lt(121), 'Brotacion primaveral',
    ee.Algorithms.If(doy.lt(182), 'Floracion y cuajado',
    ee.Algorithms.If(doy.lt(274), 'Desarrollo del fruto',
    ee.Algorithms.If(doy.lt(335), 'Maduracion y cosecha',
    'Post-cosecha')))));
  
  var vinaPhases = ee.Algorithms.If(
    doy.lt(91), 'Dormancia',
    ee.Algorithms.If(doy.lt(152), 'Brotacion y crecimiento',
    ee.Algorithms.If(doy.lt(213), 'Floracion y envero',
    ee.Algorithms.If(doy.lt(274), 'Maduracion',
    ee.Algorithms.If(doy.lt(305), 'Vendimia',
    'Senescencia')))));
  
  var almendroPhases = ee.Algorithms.If(
    doy.lt(60), 'Dormancia/Floracion',
    ee.Algorithms.If(doy.lt(121), 'Desarrollo foliar',
    ee.Algorithms.If(doy.lt(182), 'Plena vegetacion',
    ee.Algorithms.If(doy.lt(244), 'Llenado de grano',
    ee.Algorithms.If(doy.lt(274), 'Cosecha',
    'Senescencia')))));
  
  return ee.Algorithms.If(
    ee.String(cropType).equals('olivo'), olivoPhases,
    ee.Algorithms.If(
      ee.String(cropType).equals('vina'), vinaPhases,
      ee.Algorithms.If(
        ee.String(cropType).equals('almendro'), almendroPhases,
        'No definida'
      )
    )
  );
}
'''

DATA_ACQUISITION = '''
// ===================== DATA ACQUISITION ======================

// Sentinel-2 Surface Reflectance (Harmonized)
var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi)
  .filterDate(START_DATE, END_DATE)
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
  .map(function(img) {
    var qa = img.select('QA60');
    var cloudMask = qa.bitwiseAnd(1 << 10).eq(0)
      .and(qa.bitwiseAnd(1 << 11).eq(0));
    var scl = img.select('SCL');
    var validMask = scl.neq(3).and(scl.neq(8)).and(scl.neq(9)).and(scl.neq(10));
    return img.updateMask(cloudMask.and(validMask))
      .divide(10000)
      .copyProperties(img, ['system:time_start']);
  });

// Landsat 8
var l8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
  .filterBounds(roi)
  .filterDate(START_DATE, END_DATE)
  .filter(ee.Filter.lt('CLOUD_COVER', 20))
  .map(function(img) {
    var opticalBands = img.select(['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'])
      .multiply(0.0000275).add(-0.2)
      .rename(['B2', 'B3', 'B4', 'B8', 'B11', 'B12']);
    var qa = img.select('QA_PIXEL');
    var cloudMask = qa.bitwiseAnd(1 << 3).eq(0)
      .and(qa.bitwiseAnd(1 << 4).eq(0));
    return opticalBands.updateMask(cloudMask)
      .copyProperties(img, ['system:time_start']);
  });

// Landsat 9
var l9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
  .filterBounds(roi)
  .filterDate(START_DATE, END_DATE)
  .filter(ee.Filter.lt('CLOUD_COVER', 20))
  .map(function(img) {
    var opticalBands = img.select(['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'])
      .multiply(0.0000275).add(-0.2)
      .rename(['B2', 'B3', 'B4', 'B8', 'B11', 'B12']);
    var qa = img.select('QA_PIXEL');
    var cloudMask = qa.bitwiseAnd(1 << 3).eq(0)
      .and(qa.bitwiseAnd(1 << 4).eq(0));
    return opticalBands.updateMask(cloudMask)
      .copyProperties(img, ['system:time_start']);
  });

// Merge all optical collections
var IC = s2.merge(l8).merge(l9);

print('📡 Optical images found:', IC.size());

var LAST = IC.sort('system:time_start', false).first().clip(roi);

// Date info for phenological context
var lastImageDate = ee.Date(LAST.get('system:time_start'));
var currentDOY = lastImageDate.getRelative('day', 'year');
var currentYear = lastImageDate.get('year');

print('📅 Last image date:', lastImageDate.format('YYYY-MM-dd'));
print('📆 Day of Year (DOY):', currentDOY);
'''

VEGETATION_INDICES = '''
// ===================== VEGETATION INDICES ======================

function addIndices(image) {
  var hasS2 = image.bandNames().contains('B8');
  
  var out = ee.Image(ee.Algorithms.If(
    hasS2,
    (function() {
      var nir = image.select('B8');
      var red = image.select('B4');
      var blue = image.select('B2');
      
      var ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI');
      var ndwi = image.normalizedDifference(['B8', 'B11']).rename('NDWI');
      var evi = image.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {NIR: nir, RED: red, BLUE: blue}
      ).rename('EVI');
      
      var ndci = ee.Algorithms.If(
        image.bandNames().contains('B5'),
        image.normalizedDifference(['B5', 'B4']).rename('NDCI'),
        ndvi.rename('NDCI')
      );
      
      var L = 0.5;
      var savi = nir.subtract(red)
        .divide(nir.add(red).add(L))
        .multiply(1 + L)
        .rename('SAVI');
      
      var osavi = nir.subtract(red)
        .divide(nir.add(red).add(0.16))
        .multiply(1.16)
        .rename('OSAVI');
      
      return image.addBands([ndvi, ndwi, evi, ee.Image(ndci), savi, osavi]);
    })(),
    image
  ));
  
  return out.clip(roi);
}

var indexed_LAST = addIndices(LAST);
var indexedCol = IC.map(addIndices);
'''

VISUALIZATION = '''
// ===================== VISUALIZATION ======================

var vizNDVI = {
  min: 0.0, max: 0.8,
  palette: ['8B0000', 'FF0000', 'FF6347', 'FFA500', 'FFFF00',
            'ADFF2F', '7CFC00', '32CD32', '228B22', '006400']
};

var vizNDWI = {
  min: -0.3, max: 0.4,
  palette: ['8B4513', 'D2691E', 'F4A460', 'FFF8DC', 'E0FFFF',
            '87CEEB', '4682B4', '0000CD', '00008B']
};

var vizEVI = {
  min: 0.0, max: 0.6,
  palette: ['8B0000', 'CD5C5C', 'F08080', 'FFFFE0', 'ADFF2F',
            '7FFF00', '32CD32', '228B22', '006400']
};

Map.addLayer(indexed_LAST.select('NDVI'), vizNDVI, '1. 🌿 NDVI (Vigor)', true, 0.8);
Map.addLayer(indexed_LAST.select('NDWI'), vizNDWI, '2. 💧 NDWI (Agua)', false, 0.8);
Map.addLayer(indexed_LAST.select('EVI'), vizEVI, '3. 📈 EVI (Productividad)', false, 0.8);
'''

GEOTIFF_EXPORTS = '''
// ===================== EXPORT GEOTIFF ======================

var indicesToExport = ['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI', 'OSAVI'];

indicesToExport.forEach(function(bandName) {
  Export.image.toDrive({
    image: indexed_LAST.select(bandName),
    description: 'MAPA_ULTIMO_' + bandName + '_' + JOB_ID,
    fileNamePrefix: 'MAPA_ULTIMO_' + bandName + '_' + JOB_ID,
    folder: OUT_FOLDER_INDICES,
    region: roi,
    scale: 10,
    maxPixels: 1e9,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true}
  });
});
'''

TIME_SERIES = '''
// ===================== TIME SERIES ======================

var TS_ALL = indexedCol.select(['NDVI', 'NDWI', 'EVI']).map(function(img) {
  var stats = img.reduceRegion({
    reducer: ee.Reducer.mean()
      .combine(ee.Reducer.percentile([10, 50, 90]), '', true)
      .combine(ee.Reducer.stdDev(), '', true),
    geometry: roi,
    scale: 20,
    maxPixels: 1e9
  });
  
  var date = ee.Date(img.get('system:time_start'));
  
  return ee.Feature(null, {
    'date': date.format('YYYY-MM-dd'),
    'timestamp': date.millis(),
    'doy': date.getRelative('day', 'year'),
    'NDVI_mean': stats.get('NDVI_mean'),
    'NDVI_p10': stats.get('NDVI_p10'),
    'NDVI_p50': stats.get('NDVI_p50'),
    'NDVI_p90': stats.get('NDVI_p90'),
    'NDVI_stdDev': stats.get('NDVI_stdDev'),
    'NDWI_mean': stats.get('NDWI_mean'),
    'EVI_mean': stats.get('EVI_mean')
  });
});

Export.table.toDrive({
  collection: TS_ALL,
  description: 'TS_ALL_INDICES_' + JOB_ID,
  fileNamePrefix: 'TS_ALL_INDICES_' + JOB_ID,
  folder: OUT_FOLDER_GRAFICS,
  fileFormat: 'CSV'
});

var TS_NDVI = TS_ALL;
'''

KPIS_WITH_PHENOLOGY = '''
// ===================== KPIs + PHENOLOGY ======================

var lastStats = indexed_LAST.select(['NDVI', 'NDWI', 'EVI', 'SAVI', 'OSAVI']).reduceRegion({
  reducer: ee.Reducer.mean()
    .combine(ee.Reducer.percentile([10, 50, 90]), '', true)
    .combine(ee.Reducer.stdDev(), '', true),
  geometry: roi,
  scale: 10,
  maxPixels: 1e9
});

// Stress area (NDVI < 0.35)
var stressMask = indexed_LAST.select('NDVI').lt(0.35);
var stressArea = stressMask.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(),
  geometry: roi,
  scale: 10,
  maxPixels: 1e9
}).get('NDVI');

var areaHa = roi.area().divide(1e4);
var stressHa = ee.Number(stressArea).divide(1e4);
var stressPct = stressHa.divide(areaHa).multiply(100);

// Original z-score (vs all history)
var ndvi_series_mean = ee.Number(TS_NDVI.aggregate_mean('NDVI_mean'));
var ndvi_series_std = ee.Number(TS_NDVI.aggregate_total_sd('NDVI_mean'));
var ndvi_now = ee.Number(lastStats.get('NDVI_mean'));

var ndvi_z = ee.Algorithms.If(
  ndvi_series_std.gt(0),
  ndvi_now.subtract(ndvi_series_mean).divide(ndvi_series_std),
  0
);

// ---------- SEASONAL Z-SCORE (±21 days window, previous years) ----------
var windowDays = 21;
var doyMin = currentDOY.subtract(windowDays);
var doyMax = currentDOY.add(windowDays);

var seasonalCol = indexedCol.filter(
  ee.Filter.and(
    ee.Filter.dayOfYear(doyMin, doyMax),
    ee.Filter.lt('system:time_start', ee.Date.fromYMD(currentYear, 1, 1))
  )
);

var seasonalNDVI = seasonalCol.select('NDVI').map(function(img) {
  var mean = img.reduceRegion({
    reducer: ee.Reducer.mean(),
    geometry: roi,
    scale: 20,
    maxPixels: 1e9
  }).get('NDVI');
  return ee.Feature(null, {'NDVI_mean': mean});
});

var seasonalCount = seasonalNDVI.size();
var seasonalMean = ee.Number(seasonalNDVI.aggregate_mean('NDVI_mean'));
var seasonalStd = ee.Number(seasonalNDVI.aggregate_total_sd('NDVI_mean'));

var ndvi_zscore_seasonal = ee.Algorithms.If(
  seasonalCount.gte(3).and(seasonalStd.gt(0.001)),
  ndvi_now.subtract(seasonalMean).divide(seasonalStd),
  null
);

print('📊 Seasonal comparison images:', seasonalCount);

// ---------- EXPECTED NDVI (phenological curve) ----------
var ndvi_expected = getExpectedNDVI(CROP_TYPE, currentDOY);

var ndvi_deviation = ee.Algorithms.If(
  ndvi_expected,
  ndvi_now.subtract(ee.Number(ndvi_expected)),
  null
);

var ndvi_deviation_pct = ee.Algorithms.If(
  ndvi_expected,
  ee.Number(ndvi_deviation).divide(ee.Number(ndvi_expected)).multiply(100),
  null
);

// ---------- PHENOLOGICAL STATUS ----------
var pheno_status = ee.Algorithms.If(
  ndvi_expected,
  ee.Algorithms.If(
    ee.Number(ndvi_deviation_pct).gt(15),
    'adelantado',
    ee.Algorithms.If(
      ee.Number(ndvi_deviation_pct).gt(-10),
      'normal',
      ee.Algorithms.If(
        ee.Number(ndvi_deviation_pct).gt(-25),
        'retrasado',
        'critico'
      )
    )
  ),
  // Fallback for 'otro' crop - use seasonal z-score
  ee.Algorithms.If(
    ndvi_zscore_seasonal,
    ee.Algorithms.If(
      ee.Number(ndvi_zscore_seasonal).gt(1),
      'adelantado',
      ee.Algorithms.If(
        ee.Number(ndvi_zscore_seasonal).gt(-1),
        'normal',
        ee.Algorithms.If(
          ee.Number(ndvi_zscore_seasonal).gt(-2),
          'retrasado',
          'critico'
        )
      )
    ),
    'sin_datos'
  )
);

var pheno_phase = getPhenologicalPhase(CROP_TYPE, currentDOY);

print('🌱 Phenological phase:', pheno_phase);
print('📊 Expected NDVI:', ndvi_expected);
print('🚦 Phenological status:', pheno_status);

// ---------- CONSOLIDATED KPIs EXPORT ----------
var kpiFeature = ee.Feature(null, {
  'job_id': JOB_ID,
  'fecha_analisis': lastImageDate.format('YYYY-MM-dd'),
  'doy': currentDOY,
  'crop_type': CROP_TYPE,
  'area_total_ha': areaHa,
  
  // NDVI - Current
  'ndvi_mean': lastStats.get('NDVI_mean'),
  'ndvi_p10': lastStats.get('NDVI_p10'),
  'ndvi_p50': lastStats.get('NDVI_p50'),
  'ndvi_p90': lastStats.get('NDVI_p90'),
  'ndvi_stddev': lastStats.get('NDVI_stdDev'),
  'ndvi_zscore': ndvi_z,
  
  // NDVI - Seasonal comparison
  'ndvi_seasonal_mean': seasonalMean,
  'ndvi_seasonal_std': seasonalStd,
  'ndvi_seasonal_count': seasonalCount,
  'ndvi_zscore_seasonal': ndvi_zscore_seasonal,
  
  // NDVI - Phenological comparison
  'ndvi_expected': ndvi_expected,
  'ndvi_deviation': ndvi_deviation,
  'ndvi_deviation_pct': ndvi_deviation_pct,
  
  // Phenological context
  'pheno_phase': pheno_phase,
  'pheno_status': pheno_status,
  
  // Other indices
  'ndwi_mean': lastStats.get('NDWI_mean'),
  'ndwi_p10': lastStats.get('NDWI_p10'),
  'ndwi_p90': lastStats.get('NDWI_p90'),
  'evi_mean': lastStats.get('EVI_mean'),
  'evi_p10': lastStats.get('EVI_p10'),
  'evi_p90': lastStats.get('EVI_p90'),
  'savi_mean': lastStats.get('SAVI_mean'),
  'osavi_mean': lastStats.get('OSAVI_mean'),
  
  // Stress
  'area_estres_ha': stressHa,
  'area_estres_pct': stressPct,
  
  // Quality
  'num_imagenes': IC.size()
});

Export.table.toDrive({
  collection: ee.FeatureCollection([kpiFeature]),
  description: 'KPIs_CONSOLIDATED_' + JOB_ID,
  fileNamePrefix: 'KPIs_CONSOLIDATED_' + JOB_ID,
  folder: OUT_FOLDER_GRAFICS,
  fileFormat: 'CSV'
});
'''

VRA_ZONING = '''
// ===================== VRA ZONING (K-MEANS) ======================

var trainingBands = ['NDVI', 'EVI', 'NDWI'];
var trainingImage = indexed_LAST.select(trainingBands);

var validMask = trainingImage.mask().reduce(ee.Reducer.min());
var trainingImageMasked = trainingImage.updateMask(validMask);

var sample = trainingImageMasked.sample({
  region: roi,
  scale: 20,
  numPixels: 5000,
  geometries: false
});

var clusterer = ee.Clusterer.wekaKMeans(3).train(sample);
var vra = trainingImageMasked.cluster(clusterer).rename('zone');

var vraViz = {min: 1, max: 3, palette: ['red', 'yellow', 'green']};
Map.addLayer(vra, vraViz, '6. 🎯 Zonas VRA', false, 0.6);

Export.image.toDrive({
  image: vra.unmask(0).byte(),
  description: 'ZONAS_VRA3_RASTER_' + JOB_ID,
  fileNamePrefix: 'ZONAS_VRA3_RASTER_' + JOB_ID,
  folder: OUT_FOLDER_PRESCR,
  region: roi,
  scale: 10,
  maxPixels: 1e9,
  fileFormat: 'GeoTIFF'
});

var vraVectors = vra.reduceToVectors({
  geometry: roi,
  scale: 20,
  geometryType: 'polygon',
  labelProperty: 'zone',
  maxPixels: 1e9
});

Export.table.toDrive({
  collection: vraVectors,
  description: 'ZONAS_VRA3_VECTOR_' + JOB_ID,
  fileNamePrefix: 'ZONAS_VRA3_VECTOR_' + JOB_ID,
  folder: OUT_FOLDER_PRESCR,
  fileFormat: 'SHP'
});
'''

THERMAL_ANALYSIS = '''
// ===================== THERMAL ANALYSIS ======================

var modis = ee.ImageCollection('MODIS/061/MOD11A2')
  .filterDate(START_DATE, END_DATE)
  .filterBounds(roi)
  .select('LST_Day_1km');

var modisLST_C = modis.map(function(img) {
  return img.multiply(0.02).subtract(273.15)
    .rename('LST_C')
    .copyProperties(img, ['system:time_start']);
});

var LST_MED = modisLST_C.median().clip(roi);

var vizLST = {
  min: 15, max: 45,
  palette: ['0000FF', '00FFFF', '00FF00', 'FFFF00', 'FF0000']
};

Map.addLayer(LST_MED, vizLST, '7. 🌡️ LST MODIS (°C)', false, 0.7);

Export.image.toDrive({
  image: LST_MED,
  description: 'MAPA_LST_MODIS_' + JOB_ID,
  fileNamePrefix: 'MAPA_LST_MODIS_' + JOB_ID,
  folder: OUT_FOLDER_INDICES,
  region: roi,
  scale: 1000,
  maxPixels: 1e9,
  fileFormat: 'GeoTIFF'
});

// ERA5 Climate Data
var era5 = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
  .filterDate(START_DATE, END_DATE)
  .filterBounds(roi)
  .select('temperature_2m_max');

var era5_tmax = era5.map(function(img) {
  return img.subtract(273.15).rename('Tmax_C')
    .copyProperties(img, ['system:time_start']);
});

var fc_TMAX = era5_tmax.map(function(img) {
  var stats = img.reduceRegion({
    reducer: ee.Reducer.mean(),
    geometry: roi,
    scale: 11132,
    maxPixels: 1e9
  });
  return ee.Feature(null, {
    'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
    'tmax_c': stats.get('Tmax_C')
  });
});

Export.table.toDrive({
  collection: fc_TMAX,
  description: 'TS_DAILY_TMAX_ERA5_' + JOB_ID,
  fileNamePrefix: 'TS_DAILY_TMAX_ERA5_' + JOB_ID,
  folder: OUT_FOLDER_GRAFICS,
  fileFormat: 'CSV'
});
'''

SUMMARY = '''
// ===================== SUMMARY ======================

print('');
print('✅ ========== PROCESSING COMPLETE (v3.2 - Phenology) ==========');
print('📊 JOB_ID:', JOB_ID);
print('🌱 Crop type:', CROP_TYPE);
print('📅 Last image:', lastImageDate.format('YYYY-MM-dd'));
print('📆 DOY:', currentDOY);
print('');
print('🆕 NEW KPI FIELDS IN CSV:');
print('  • ndvi_expected - Expected NDVI for crop/date');
print('  • ndvi_deviation_pct - % deviation from expected');
print('  • ndvi_zscore_seasonal - Z-score vs same period prev years');
print('  • pheno_phase - Current phenological phase');
print('  • pheno_status - adelantado/normal/retrasado/critico');
print('');
print('📤 Exports queued (check Tasks tab):');
print('  ✔ 6 GeoTIFF maps');
print('  ✔ 1 LST map');
print('  ✔ 2 VRA files');
print('  ✔ 1 time series CSV');
print('  ✔ 1 thermal CSV');
print('  ✔ 1 KPIs CSV (WITH PHENOLOGY)');
'''


# ============================================================================
# TESTS
# ============================================================================

if __name__ == "__main__":
    # Test básico
    test_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [-6.192790515087148, 36.66142740600855],
            [-6.172362811229726, 36.655643665060126],
            [-6.17425108637621, 36.665282991898934],
            [-6.192790515087148, 36.66142740600855]
        ]]
    }
    
    script = generate_gee_script(
        job_id="TEST_PHENOLOGY_001",
        roi_geojson=test_geojson,
        crop_type="olivo",
        start_date="2025-01-01",
        end_date="2025-12-15"
    )
    
    print("=" * 60)
    print("Script generado correctamente!")
    print("=" * 60)
    print(f"Longitud: {len(script)} caracteres")
    print(f"Contiene CROP_TYPE = 'olivo': {'olivo' in script}")
    print(f"Contiene getExpectedNDVI_Olivo: {'getExpectedNDVI_Olivo' in script}")
    print(f"Contiene pheno_status: {'pheno_status' in script}")
    print("=" * 60)
    
    # Guardar para inspección
    with open("/tmp/test_gee_script.js", "w") as f:
        f.write(script)
    print("Script guardado en /tmp/test_gee_script.js")
