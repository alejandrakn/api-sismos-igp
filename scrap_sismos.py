import json
import uuid
from datetime import datetime

import boto3
import requests

LIMITE = None   # None = guardar todos los reportes del año | 10 = solo los 10 últimos
URL = "https://ultimosismo.igp.gob.pe/api/ultimo-sismo/ajaxb/{anio}"
HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': '*/*',
    'Referer': 'https://ultimosismo.igp.gob.pe/productos/reportes-sismicos'
}


def obtener_sismos(anio):
    response = requests.get(URL.format(anio=anio), headers=HEADERS, timeout=20)
    if response.status_code != 200:
        return response.status_code, None
    data = response.json()
    if isinstance(data, dict):                       # por si viene envuelto
        data = data.get('data') or data.get('sismos') or []
    return 200, data


def clave_orden(s):
    """Más reciente primero: fecha local + hora local + código del reporte."""
    fecha = str(s.get('fecha_local') or s.get('fecha_utc') or '')[:10]
    hora = str(s.get('hora_local') or s.get('hora_utc') or '')
    hora = hora[11:19] if 'T' in hora else hora[:8]
    codigo = str(s.get('codigo') or s.get('reporte') or s.get('id') or '')
    return (fecha, hora, codigo)


def a_item(sismo):
    """DynamoDB no acepta float ni vacíos: todo a string."""
    item = {}
    for k, v in sismo.items():
        if v is None or v == '':
            continue
        item[k] = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
    return item


def lambda_handler(event, context):
    # Solicitar los datos del año actual
    anio = datetime.now().year
    status, sismos = obtener_sismos(anio)
    if status != 200:
        return {
            'statusCode': status,
            'body': 'Error al acceder a la página web'
        }
    if not sismos:
        return {
            'statusCode': 404,
            'body': 'No se encontraron sismos en la respuesta'
        }

    # Ordenar del más reciente al más antiguo (y limitar si corresponde)
    sismos = sorted(sismos, key=clave_orden, reverse=True)
    if LIMITE:
        sismos = sismos[:LIMITE]

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('TablaSismosIGP')

    # Eliminar todos los elementos de la tabla antes de agregar los nuevos
    # (el scan está paginado: devuelve máx. 1 MB por llamada)
    items_viejos = []
    scan = table.scan()
    items_viejos.extend(scan['Items'])
    while 'LastEvaluatedKey' in scan:
        scan = table.scan(ExclusiveStartKey=scan['LastEvaluatedKey'])
        items_viejos.extend(scan['Items'])

    with table.batch_writer() as batch:
        for each in items_viejos:
            batch.delete_item(Key={'id': each['id']})

    # Insertar los nuevos datos (batch_writer agrupa en lotes de 25)
    rows = []
    i = 1
    with table.batch_writer() as batch:
        for sismo in sismos:
            row = a_item(sismo)
            row['#'] = i
            row['id'] = str(uuid.uuid4())  # ID único (reemplaza el id del IGP)
            batch.put_item(Item=row)
            rows.append(row)
            i = i + 1

    # Retornar un resumen (no los 758 registros, para que la respuesta sea corta)
    return {
        'statusCode': 200,
        'total': len(rows),
        'body': rows[:10]
    }
