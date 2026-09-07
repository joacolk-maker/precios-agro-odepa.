"""
Script de actualizacion automatica: descarga el CSV publico de ODEPA
(precios mayoristas de fruta y hortaliza), calcula un hash unico por
fila y sube a Supabase solo las filas que todavia no existen.

Habla directo con la API REST de Supabase usando "requests" (sin la
libreria "supabase"), para tener control total sobre la direccion web
que se arma y evitar comportamientos raros de librerias intermedias.
"""

import os
import io
import csv
import hashlib
import requests

# URL publica del CSV de ODEPA (se actualiza todos los dias con datos nuevos)
CSV_URL = (
    "https://datos.odepa.gob.cl/dataset/33f10516-acbe-4446-b633-68244b9b6b26/"
    "resource/580beca0-e87e-4dd4-9e8a-0bd92773f4a6/download/"
    "precio_mayorista_fruta-hortaliza_2026.csv"
)

# Nombre exacto de la tabla en Supabase (sin espacios, ya renombrada)
TABLE_NAME = "precios_raw"

# Credenciales desde los "Secrets" de GitHub. .strip() y .rstrip("/") limpian
# cualquier espacio, salto de linea o barra final que se haya colado sin querer.
SUPABASE_URL = os.environ["SUPABASE_URL"].strip().rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"].strip()

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def calcular_hash(row: dict) -> str:
    """Genera un codigo unico (hash) a partir de todos los datos de una fila."""
    campos = [
        row.get("Fecha", ""),
        row.get("ID region", ""),
        row.get("Region", ""),
        row.get("Mercado", ""),
        row.get("Subsector", ""),
        row.get("Producto", ""),
        row.get("Variedad / Tipo", ""),
        row.get("Calidad", ""),
        row.get("Unidad de comercializacion", ""),
        row.get("Origen", ""),
        row.get("Volumen", ""),
        row.get("Precio minimo", ""),
        row.get("Precio maximo", ""),
        row.get("Precio promedio", ""),
    ]
    texto = "|".join(str(c).strip() for c in campos)
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def a_entero(valor):
    """Convierte a numero entero de forma segura; si esta vacio devuelve None."""
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return int(valor)
    except ValueError:
        return None


def insertar_lote(lote):
    """Sube un lote de filas. Las que ya existen (mismo hash_fila) se ignoran
    gracias al header 'Prefer: resolution=ignore-duplicates' combinado con
    el parametro on_conflict."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = dict(HEADERS)
    headers["Prefer"] = "resolution=ignore-duplicates,return=representation"
    params = {"on_conflict": "hash_fila"}

    respuesta = requests.post(url, headers=headers, params=params, json=lote, timeout=60)
    if not respuesta.ok:
        print("Respuesta de error de Supabase:", respuesta.status_code, respuesta.text)
    respuesta.raise_for_status()
    return respuesta.json()


def refrescar_vista():
    """Llama a la funcion de Postgres que refresca la vista precios_web."""
    url = f"{SUPABASE_URL}/rest/v1/rpc/refrescar_precios_web"
    respuesta = requests.post(url, headers=HEADERS, json={}, timeout=120)
    if not respuesta.ok:
        print("Respuesta de error al refrescar la vista:", respuesta.status_code, respuesta.text)
    respuesta.raise_for_status()


def main():
    print("Descargando CSV desde ODEPA...")
    respuesta = requests.get(CSV_URL, timeout=60)
    respuesta.raise_for_status()

    # utf-8-sig elimina el caracter invisible (BOM) que a veces trae el archivo
    contenido = respuesta.content.decode("utf-8-sig")
    lector = csv.DictReader(io.StringIO(contenido))

    filas = []
    for row in lector:
        fila = {
            "Fecha": row.get("Fecha") or None,
            "ID region": a_entero(row.get("ID region")),
            "Region": row.get("Region"),
            "Mercado": row.get("Mercado"),
            "Subsector": row.get("Subsector"),
            "Producto": row.get("Producto"),
            "Variedad / Tipo": row.get("Variedad / Tipo"),
            "Calidad": row.get("Calidad"),
            "Unidad de comercializacion": row.get("Unidad de comercializacion"),
            "Origen": row.get("Origen"),
            "Volumen": a_entero(row.get("Volumen")),
            "Precio minimo": row.get("Precio minimo"),
            "Precio maximo": row.get("Precio maximo"),
            "Precio promedio": row.get("Precio promedio"),
            "hash_fila": calcular_hash(row),
        }
        filas.append(fila)

    print(f"Filas leidas del CSV: {len(filas)}")

    tamano_lote = 500
    total_nuevas = 0
    for inicio in range(0, len(filas), tamano_lote):
        lote = filas[inicio:inicio + tamano_lote]
        resultado = insertar_lote(lote)
        nuevas_en_lote = len(resultado) if resultado else 0
        total_nuevas += nuevas_en_lote
        print(f"Lote {inicio // tamano_lote + 1}: {nuevas_en_lote} filas nuevas insertadas")

    print(f"Listo. Total de filas nuevas agregadas hoy: {total_nuevas}")

    print("Refrescando la vista precios_web...")
    refrescar_vista()
    print("Vista precios_web actualizada.")


if __name__ == "__main__":
    main()
