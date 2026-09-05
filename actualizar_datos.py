"""
Script de actualizacion automatica: descarga el CSV publico de ODEPA
(precios mayoristas de fruta y hortaliza), calcula un hash unico por
fila y sube a Supabase solo las filas que todavia no existen.

No necesitas entender cada linea para usarlo: este archivo se sube tal
cual al repositorio de GitHub, y un flujo de GitHub Actions lo ejecuta
automaticamente todos los dias.
"""

import os
import io
import csv
import hashlib
import requests
from supabase import create_client

# URL publica del CSV de ODEPA (se actualiza todos los dias con datos nuevos)
CSV_URL = (
    "https://datos.odepa.gob.cl/dataset/33f10516-acbe-4446-b633-68244b9b6b26/"
    "resource/580beca0-e87e-4dd4-9e8a-0bd92773f4a6/download/"
    "precio_mayorista_fruta-hortaliza_2026.csv"
)

# Nombre exacto de la tabla en Supabase (con espacios y mayusculas, tal cual quedo creada)
TABLE_NAME = "Tabla Raw Odepa"

# Credenciales: se leen desde los "Secrets" de GitHub, nunca quedan escritas en este archivo
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def calcular_hash(row: dict) -> str:
    """Genera un codigo unico (hash) a partir de todos los datos de una fila.
    Filas con exactamente los mismos datos generan el mismo hash, lo que nos
    permite detectar y evitar filas duplicadas al recargar el CSV."""
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

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Subimos en lotes de 500 filas. on_conflict="hash_fila" hace que, si una
    # fila ya existe (mismo hash), Supabase simplemente la ignore en vez de
    # duplicarla o fallar.
    tamano_lote = 500
    total_nuevas = 0
    for inicio in range(0, len(filas), tamano_lote):
        lote = filas[inicio:inicio + tamano_lote]
        resultado = (
            supabase.table(TABLE_NAME)
            .upsert(lote, on_conflict="hash_fila", ignore_duplicates=True)
            .execute()
        )
        nuevas_en_lote = len(resultado.data) if resultado.data else 0
        total_nuevas += nuevas_en_lote
        print(f"Lote {inicio // tamano_lote + 1}: {nuevas_en_lote} filas nuevas insertadas")

    print(f"Listo. Total de filas nuevas agregadas hoy: {total_nuevas}")

    # Refresca la vista precios_web para que refleje los datos nuevos.
    # Se hace siempre (incluso si total_nuevas es 0) para mantener todo simple;
    # como usa CONCURRENTLY no bloquea a nadie que este consultando la web.
    print("Refrescando la vista precios_web...")
    supabase.rpc("refrescar_precios_web").execute()
    print("Vista precios_web actualizada.")


if __name__ == "__main__":
    main()
