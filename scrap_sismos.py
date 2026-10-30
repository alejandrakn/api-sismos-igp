import uuid
from datetime import datetime

import boto3
import requests

TABLE_NAME = 'TablaSismosIGP'
CANTIDAD = 10

# La página reportes-sismicos es una SPA (el HTML viene vacío): los datos
# los carga por JavaScript desde un endpoint JSON. Scrapeamos ese endpoint.
# Si el IGP cambia la ruta, confírmala en DevTools > Network > Fetch/XHR.
URLS = [
    'https://ultimosismo.igp.gob.pe/ultimo-sismo/ajaxb/{anio}',
    'https://ultimosismo.igp.gob.pe/api/ultimo-sismo/ajaxb/{anio}',
]
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; UTEC-CS2032-taller/1.0)',
    'Accept': 'application/json, text/plain, */*',
    'X-Requested-With': 'XMLHttpRequest',
}


def obtener_sismos_anio(anio):
    """Devuelve la lista de sismos del año o [] si ningún endpoint responde."""
    for plantilla in URLS:
        url = plantilla.format(anio=anio)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue
        # Puede venir como lista directa o envuelta en {"data": [...]}
        if isinstance(data, dict):
            data = data.get('data') or data.get('sismos') or []
        if isinstance(data, list) and data:
            return data
    return []


def clave_orden(s):
    """Ordena por fecha/hora local (más reciente primero)."""
    try:
        return datetime.strptime(
            f"{s.get('fecha_local', '')[:10]} {s.get('hora_local', '00:00:00')}",
            '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return datetime.min


def normalizar(s):
    """DynamoDB no acepta float: todo se guarda como string."""
    campos = ['codigo', 'reporte', 'fecha_local', 'hora_local', 'fecha_utc',
              'hora_utc', 'magnitud', 'profundidad', 'latitud', 'longitud',
              'referencia', 'intensidad']
    item = {c: str(s[c]) for c in campos if s.get(c) not in (None, '')}
    item['id'] = str(uuid.uuid4())
    return item


def lambda_handler(event, context):
    anio = datetime.now().year
    sismos = obtener_sismos_anio(anio)
    if len(sismos) < CANTIDAD:                 # p. ej. a inicios de enero
        sismos += obtener_sismos_anio(anio - 1)

    if not sismos:
        return {'statusCode': 502,
                'body': 'No se pudo obtener datos del IGP (revisar endpoint)'}

    ultimos = sorted(sismos, key=clave_orden, reverse=True)[:CANTIDAD]
    items = [normalizar(s) for s in ultimos]
    for n, item in enumerate(items, start=1):
        item['#'] = n

    tabla = boto3.resource('dynamodb').Table(TABLE_NAME)

    # Igual que en el Ejercicio 1: limpiar la tabla antes de insertar
    scan = tabla.scan()
    with tabla.batch_writer() as batch:
        for each in scan['Items']:
            batch.delete_item(Key={'id': each['id']})

    with tabla.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    return {'statusCode': 200, 'body': items}
