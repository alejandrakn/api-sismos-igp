import json
import uuid
from datetime import datetime

import boto3
import requests

# Endpoint JSON que usa la propia página (visto en DevTools > Network)
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

    # Quedarse con los 10 últimos sismos
    ultimos = sorted(sismos, key=clave_orden, reverse=True)[:10]

    # Guardar los datos en DynamoDB
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('TablaSismosIGP')

    # Eliminar todos los elementos de la tabla antes de agregar los nuevos
    scan = table.scan()
    with table.batch_writer() as batch:
        for each in scan['Items']:
            batch.delete_item(
                Key={
                    'id': each['id']
                }
            )

    # Insertar los nuevos datos
    rows = []
    i = 1
    for sismo in ultimos:
        row = a_item(sismo)
        row['#'] = i
        row['id'] = str(uuid.uuid4())  # ID único (sobrescribe el id del IGP si lo hay)
        table.put_item(Item=row)
        rows.append(row)
        i = i + 1

    # Retornar el resultado como JSON
    return {
        'statusCode': 200,
        'body': rows
    }
