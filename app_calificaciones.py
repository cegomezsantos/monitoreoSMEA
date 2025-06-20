import streamlit as st
import pandas as pd
import requests
import csv
import time
import os
from datetime import datetime
import hashlib
from supabase import create_client, Client
import urllib3

# Suprimir warnings de SSL (basado en script verificado)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================
# CONFIGURACIÓN
# ==========================
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv('.env.local')

# Configuración con prioridad: Streamlit secrets > .env.local > variables de entorno
try:
    # Intentar usar Streamlit secrets primero
    MOODLE_BASE_URL = st.secrets.get('MOODLE_URL', os.getenv('MOODLE_URL', 'https://platform.ecala.net/webservice/rest/server.php'))
    MOODLE_TOKEN = st.secrets.get('MOODLE_TOKEN', os.getenv('MOODLE_TOKEN'))
    SUPABASE_URL = st.secrets.get('SUPABASE_URL', os.getenv('SUPABASE_URL'))
    SUPABASE_KEY = st.secrets.get('SUPABASE_KEY', os.getenv('SUPABASE_KEY'))
except:
    # Fallback a variables de entorno si Streamlit secrets no está disponible
    MOODLE_BASE_URL = os.getenv('MOODLE_URL', 'https://platform.ecala.net/webservice/rest/server.php')
    MOODLE_TOKEN = os.getenv('MOODLE_TOKEN')
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')

HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}

# Inicializar cliente Supabase solo si las credenciales están disponibles
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error al conectar con Supabase: {e}")
        supabase = None

# Archivos de datos
ASIGNACIONES_CSV = "asignaciones_evaluaciones.csv"
CURSOS_CSV = "cursos.csv"
CACHE_CSV = "cache_calificaciones.csv"
CACHE_MASIVO_CSV = "cache_masivo.csv"

# ==========================
# FUNCIONES SUPABASE
# ==========================
def verificar_datos_en_supabase(course_id, assignment_id):
    """Verifica si ya existen datos en Supabase para un curso y actividad específicos"""
    if not supabase:
        return False, []
    try:
        response = supabase.table('calificaciones_feedback').select('*').eq('course_id', course_id).eq('assignment_id', assignment_id).execute()
        return len(response.data) > 0, response.data
    except Exception as e:
        st.warning(f"Error al consultar Supabase: {str(e)}")
        return False, []

def guardar_datos_en_supabase(datos_lista):
    """Guarda una lista de datos en Supabase"""
    if not supabase:
        return False, 0
    try:
        # Preparar datos para inserción
        datos_para_insertar = []
        for dato in datos_lista:
            registro = {
                'course_id': dato.get('course_id'),
                'assignment_id': dato.get('assignment_id'),
                'course_name': dato.get('course_name'),
                'assignment_name': dato.get('assignment_name'),
                'docente': dato.get('docente'),
                'user_id': dato.get('user_id'),
                'user_fullname': dato.get('user_fullname'),
                'grade': str(dato.get('grade', '')),
                'feedback': dato.get('feedback', ''),
                'has_feedback': dato.get('has_feedback', False)
            }
            datos_para_insertar.append(registro)
        
        # Insertar en Supabase usando upsert para evitar duplicados
        response = supabase.table('calificaciones_feedback').upsert(
            datos_para_insertar,
            on_conflict='course_id,assignment_id,user_id'
        ).execute()
        
        return True, len(response.data)
    except Exception as e:
        st.error(f"Error al guardar en Supabase: {str(e)}")
        return False, 0

def obtener_datos_de_supabase(course_id, assignment_id):
    """Obtiene datos específicos de Supabase"""
    if not supabase:
        return pd.DataFrame()
    try:
        response = supabase.table('calificaciones_feedback').select('*').eq('course_id', course_id).eq('assignment_id', assignment_id).execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error al obtener datos de Supabase: {str(e)}")
        return pd.DataFrame()

def obtener_datos_masivos_supabase(filtros):
    """Obtiene datos masivos de Supabase con filtros"""
    if not supabase:
        return pd.DataFrame()
    try:
        query = supabase.table('calificaciones_feedback').select('*')
        
        # Aplicar filtros
        if 'course_ids' in filtros and filtros['course_ids']:
            query = query.in_('course_id', filtros['course_ids'])
        
        if 'docente' in filtros and filtros['docente']:
            query = query.eq('docente', filtros['docente'])
        
        if 'course_name' in filtros and filtros['course_name']:
            query = query.eq('course_name', filtros['course_name'])
            
        response = query.execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error al obtener datos masivos de Supabase: {str(e)}")
        return pd.DataFrame()

def verificar_conexion_supabase():
    """Verifica si la conexión a Supabase funciona"""
    if not supabase:
        return False
    try:
        response = supabase.table('calificaciones_feedback').select('id').limit(1).execute()
        return True
    except Exception as e:
        st.error(f"Error de conexión a Supabase: {str(e)}")
        return False

# ==========================
# FUNCIONES AUXILIARES MOODLE
# ==========================
def llamar_ws(params: dict) -> dict:
    """Envía petición POST al endpoint REST de Moodle"""
    resp = requests.post(MOODLE_BASE_URL, data=params, headers=HEADERS, verify=False)
    resp.raise_for_status()
    return resp.json()

def obtener_nombre_assignment(course_id: int, assignment_id: int) -> str:
    """Obtiene el nombre de la assignment"""
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "mod_assign_get_assignments",
        "moodlewsrestformat": "json",
        "courseids[0]": course_id
    }
    resultado = llamar_ws(params)
    courses = resultado.get("courses", [])
    for curso in courses:
        assignments = curso.get("assignments", [])
        for a in assignments:
            if a.get("id") == assignment_id:
                return a.get("name", "")
    return ""

def obtener_grades(assignment_id: int) -> dict:
    """Obtiene calificaciones para una assignment"""
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "mod_assign_get_grades",
        "moodlewsrestformat": "json",
        "assignmentids[0]": assignment_id
    }
    resultado = llamar_ws(params)
    grades = {}
    assignments = resultado.get("assignments", [])
    if assignments:
        for g in assignments[0].get("grades", []):
            userid = g.get("userid")
            grades[userid] = g.get("grade")
    return grades

def obtener_ids_participantes(assignment_id: int) -> list:
    """Obtiene lista de participantes"""
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "mod_assign_list_participants",
        "moodlewsrestformat": "json",
        "assignid": assignment_id,
        "groupid": 0,
        "filter": "",
        "includeenrolments": 1
    }
    resultado = llamar_ws(params)
    
    if isinstance(resultado, dict) and resultado.get("exception"):
        st.error(f"Error en mod_assign_list_participants: {resultado.get('message')}")
        return []
    
    usuarios = resultado if isinstance(resultado, list) else resultado.get("users", [])
    participantes = []
    for u in usuarios:
        uid = u.get("id")
        fullname = u.get("fullname", "")
        participantes.append({"id": uid, "fullname": fullname})
    return participantes

def obtener_feedback(assignment_id: int, user_id: int) -> str:
    """Obtiene feedback para un estudiante específico"""
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "mod_assign_get_submission_status",
        "moodlewsrestformat": "json",
        "assignid": assignment_id,
        "userid": user_id,
        "groupid": 0
    }
    resultado = llamar_ws(params)
    plugins = resultado.get("feedback", {}).get("plugins", [])
    for plugin in plugins:
        if plugin.get("type") == "comments":
            editorfields = plugin.get("editorfields", [])
            if editorfields:
                return editorfields[0].get("text", "")
    return ""

# ==========================
# FUNCIONES DE CACHE
# ==========================
def crear_cache_key(course_id, assignment_id):
    """Crea una clave única para el cache"""
    return hashlib.md5(f"{course_id}_{assignment_id}".encode()).hexdigest()

def crear_cache_key_masivo(identificador):
    """Crea una clave única para el cache masivo"""
    return hashlib.md5(f"masivo_{identificador}".encode()).hexdigest()

def existe_en_cache(course_id, assignment_id):
    """Verifica si ya existe data en cache"""
    if not os.path.exists(CACHE_CSV):
        return False
    
    cache_df = pd.read_csv(CACHE_CSV)
    cache_key = crear_cache_key(course_id, assignment_id)
    return cache_key in cache_df['cache_key'].values

def existe_en_cache_masivo(identificador):
    """Verifica si ya existe data en cache masivo"""
    if not os.path.exists(CACHE_MASIVO_CSV):
        return False
    
    cache_df = pd.read_csv(CACHE_MASIVO_CSV)
    cache_key = crear_cache_key_masivo(identificador)
    return cache_key in cache_df['cache_key'].values

def obtener_de_cache(course_id, assignment_id):
    """Obtiene datos del cache"""
    cache_df = pd.read_csv(CACHE_CSV)
    cache_key = crear_cache_key(course_id, assignment_id)
    return cache_df[cache_df['cache_key'] == cache_key]

def obtener_de_cache_masivo(identificador):
    """Obtiene datos del cache masivo"""
    cache_df = pd.read_csv(CACHE_MASIVO_CSV)
    cache_key = crear_cache_key_masivo(identificador)
    return cache_df[cache_df['cache_key'] == cache_key]

def guardar_en_cache(data, course_id, assignment_id):
    """Guarda datos en cache"""
    cache_key = crear_cache_key(course_id, assignment_id)
    timestamp = datetime.now().isoformat()
    
    # Agregar metadata al dataframe
    data['cache_key'] = cache_key
    data['timestamp'] = timestamp
    data['course_id'] = course_id
    data['assignment_id'] = assignment_id
    
    # Si el archivo existe, agregamos los datos
    if os.path.exists(CACHE_CSV):
        existing_cache = pd.read_csv(CACHE_CSV)
        # Eliminar entradas existentes para este cache_key
        existing_cache = existing_cache[existing_cache['cache_key'] != cache_key]
        combined_data = pd.concat([existing_cache, data], ignore_index=True)
    else:
        combined_data = data
    
    combined_data.to_csv(CACHE_CSV, index=False)

def guardar_en_cache_masivo(data, identificador):
    """Guarda datos en cache masivo"""
    cache_key = crear_cache_key_masivo(identificador)
    timestamp = datetime.now().isoformat()
    
    # Agregar metadata al dataframe
    data['cache_key'] = cache_key
    data['timestamp'] = timestamp
    data['identificador'] = identificador
    
    # Si el archivo existe, agregamos los datos
    if os.path.exists(CACHE_MASIVO_CSV):
        existing_cache = pd.read_csv(CACHE_MASIVO_CSV)
        # Eliminar entradas existentes para este cache_key
        existing_cache = existing_cache[existing_cache['cache_key'] != cache_key]
        combined_data = pd.concat([existing_cache, data], ignore_index=True)
    else:
        combined_data = data
    
    combined_data.to_csv(CACHE_MASIVO_CSV, index=False)

# ==========================
# FUNCIÓN PRINCIPAL DE EXTRACCIÓN
# ==========================
def extraer_calificaciones_feedback(course_id, assignment_id, assignment_name, course_name, docente):
    """Extrae calificaciones y feedback, primero verifica Supabase, luego cache, finalmente Moodle"""
    
    # 1. Verificar Supabase primero
    datos_existen, datos_supabase = verificar_datos_en_supabase(course_id, assignment_id)
    if datos_existen:
        st.info("🗄️ Datos encontrados en Supabase. Cargando...")
        df_supabase = obtener_datos_de_supabase(course_id, assignment_id)
        if not df_supabase.empty:
            # Agregar campos necesarios si no existen
            if 'course_id' not in df_supabase.columns:
                df_supabase['course_id'] = course_id
            return df_supabase
    
    # 2. Verificar cache local
    if existe_en_cache(course_id, assignment_id):
        st.info("📋 Datos encontrados en cache local. Cargando...")
        return obtener_de_cache(course_id, assignment_id)
    
    # 3. Extraer de Moodle como último recurso
    st.info("🔄 Obteniendo datos de Moodle...")
    
    try:
        grades_dict = obtener_grades(assignment_id)
        participantes = obtener_ids_participantes(assignment_id)
        
        if not participantes:
            st.warning("No se encontraron participantes para esta actividad.")
            return pd.DataFrame()
        
        datos = []
        progress_bar = st.progress(0)
        
        for i, p in enumerate(participantes):
            uid = p["id"]
            fullname = p["fullname"]
            grade = grades_dict.get(uid, "")
            feedback = obtener_feedback(assignment_id, uid)
            
            datos.append({
                "course_id": course_id,
                "assignment_id": assignment_id,
                "assignment_name": assignment_name,
                "course_name": course_name,
                "docente": docente,
                "user_id": uid,
                "user_fullname": fullname,
                "grade": grade,
                "feedback": feedback,
                "has_feedback": len(str(feedback).strip()) > 0
            })
            
            # Actualizar barra de progreso
            progress_bar.progress((i + 1) / len(participantes))
        
        df = pd.DataFrame(datos)
        
        if not df.empty:
            # Guardar en Supabase
            exito_supabase, registros_guardados = guardar_datos_en_supabase(datos)
            if exito_supabase:
                st.success(f"💾 Datos guardados en Supabase: {registros_guardados} registros")
            
            # Guardar en cache local como respaldo
            guardar_en_cache(df.copy(), course_id, assignment_id)
        
        st.success(f"✅ Datos extraídos exitosamente: {len(datos)} estudiantes")
        return df
        
    except Exception as e:
        st.error(f"Error al extraer datos: {str(e)}")
        return pd.DataFrame()

def extraer_calificaciones_masivo(actividades_df, identificador):
    """Extrae calificaciones para múltiples actividades, verifica Supabase primero"""
    
    # 1. Intentar obtener datos de Supabase primero
    course_ids = actividades_df['id_curso'].unique().tolist()
    filtros_supabase = {'course_ids': course_ids}
    
    df_supabase = obtener_datos_masivos_supabase(filtros_supabase)
    actividades_en_supabase = set()
    
    if not df_supabase.empty:
        actividades_en_supabase = set(zip(df_supabase['course_id'], df_supabase['assignment_id']))
        st.info(f"🗄️ Encontrados datos en Supabase para {len(actividades_en_supabase)} actividades")
    
    # 2. Verificar cache masivo
    if existe_en_cache_masivo(identificador):
        st.info("📋 Datos encontrados en cache masivo local.")
        df_cache = obtener_de_cache_masivo(identificador)
        if not df_cache.empty:
            # Combinar datos de Supabase y cache si ambos existen
            if not df_supabase.empty:
                df_combinado = pd.concat([df_supabase, df_cache], ignore_index=True).drop_duplicates(
                    subset=['course_id', 'assignment_id', 'user_id'], keep='first'
                )
                return df_combinado
            return df_cache
    
    # 3. Determinar qué actividades necesitan ser extraídas de Moodle
    actividades_df_reset = actividades_df.reset_index(drop=True)
    actividades_faltantes = []
    
    for _, row in actividades_df_reset.iterrows():
        if (row['id_curso'], row['id']) not in actividades_en_supabase:
            actividades_faltantes.append(row)
    
    if actividades_faltantes:
        st.info(f"🔄 Extrayendo {len(actividades_faltantes)} actividades faltantes de Moodle...")
        
        try:
            todos_los_datos = []
            total_actividades = len(actividades_faltantes)
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for contador, row in enumerate(actividades_faltantes):
                course_id = row['id_curso']
                assignment_id = row['id']
                assignment_name = row['name']
                course_name = row['NomCurso']
                docente = row['DOCENTE']
                
                status_text.text(f"Procesando: {assignment_name} ({contador + 1}/{total_actividades})")
                
                try:
                    grades_dict = obtener_grades(assignment_id)
                    participantes = obtener_ids_participantes(assignment_id)
                    
                    for p in participantes:
                        uid = p["id"]
                        fullname = p["fullname"]
                        grade = grades_dict.get(uid, "")
                        
                        todos_los_datos.append({
                            "course_id": course_id,
                            "course_name": course_name,
                            "docente": docente,
                            "assignment_id": assignment_id,
                            "assignment_name": assignment_name,
                            "user_id": uid,
                            "user_fullname": fullname,
                            "grade": grade
                        })
                    
                    time.sleep(0.1)
                    
                except Exception as e:
                    st.warning(f"Error procesando {assignment_name}: {str(e)}")
                    continue
                
                progreso = min((contador + 1) / total_actividades, 1.0)
                progress_bar.progress(progreso)
            
            status_text.empty()
            progress_bar.empty()
            
            df_nuevos = pd.DataFrame(todos_los_datos)
            
            if not df_nuevos.empty:
                # Guardar nuevos datos en Supabase
                exito_supabase, registros_guardados = guardar_datos_en_supabase(todos_los_datos)
                if exito_supabase:
                    st.success(f"💾 {registros_guardados} nuevos registros guardados en Supabase")
                
                # Combinar con datos existentes de Supabase
                if not df_supabase.empty:
                    df_final = pd.concat([df_supabase, df_nuevos], ignore_index=True)
                else:
                    df_final = df_nuevos
                
                # Guardar en cache masivo
                guardar_en_cache_masivo(df_final.copy(), identificador)
                
                st.success(f"✅ Extracción completada: {len(df_final)} registros totales")
                return df_final
            
        except Exception as e:
            st.error(f"Error al extraer datos masivos: {str(e)}")
    
    # Retornar datos de Supabase si no hay actividades faltantes
    if not df_supabase.empty:
        st.success(f"✅ Todos los datos obtenidos de Supabase: {len(df_supabase)} registros")
        return df_supabase
    
    st.warning("No se pudieron obtener datos.")
    return pd.DataFrame()

def crear_matriz_calificaciones(df):
    """Convierte los datos en formato matriz: estudiantes vs actividades"""
    if df.empty:
        return pd.DataFrame()
    
    # Crear tabla pivote
    matriz = df.pivot_table(
        index=['user_fullname', 'course_name', 'docente'],
        columns='assignment_name',
        values='grade',
        aggfunc='first',
        fill_value=''
    )
    
    # Resetear índice para tener las columnas como columnas normales
    matriz = matriz.reset_index()
    
    # Ordenar columnas poniendo Evaluación Integral al final
    matriz = ordenar_columnas_evaluacion_integral(matriz)
    
    return matriz

def extraer_datos_con_feedback(actividades_df, identificador):
    """Extrae calificaciones Y feedback, verifica Supabase primero"""
    
    # 1. Intentar obtener datos completos de Supabase
    course_ids = actividades_df['id_curso'].unique().tolist()
    filtros_supabase = {'course_ids': course_ids}
    
    df_supabase = obtener_datos_masivos_supabase(filtros_supabase)
    actividades_en_supabase = set()
    
    if not df_supabase.empty:
        # Filtrar solo datos que tienen feedback
        df_supabase_completo = df_supabase[df_supabase['feedback'].notna() & (df_supabase['feedback'] != '')]
        actividades_en_supabase = set(zip(df_supabase_completo['course_id'], df_supabase_completo['assignment_id']))
        
        if not df_supabase_completo.empty:
            st.info(f"🗄️ Encontrados datos con feedback en Supabase para {len(actividades_en_supabase)} actividades")
    
    # 2. Verificar cache local
    cache_key_feedback = f"{identificador}_feedback"
    if existe_en_cache_masivo(cache_key_feedback):
        st.info("📋 Datos con feedback encontrados en cache local.")
        df_cache = obtener_de_cache_masivo(cache_key_feedback)
        if not df_cache.empty:
            # Combinar datos de Supabase y cache si ambos existen
            if not df_supabase.empty:
                df_combinado = pd.concat([df_supabase, df_cache], ignore_index=True).drop_duplicates(
                    subset=['course_id', 'assignment_id', 'user_id'], keep='first'
                )
                return df_combinado
            return df_cache
    
    # 3. Determinar qué actividades necesitan extracción completa
    actividades_df_reset = actividades_df.reset_index(drop=True)
    actividades_faltantes = []
    
    for _, row in actividades_df_reset.iterrows():
        if (row['id_curso'], row['id']) not in actividades_en_supabase:
            actividades_faltantes.append(row)
    
    if actividades_faltantes:
        st.info(f"🔄 Extrayendo {len(actividades_faltantes)} actividades con feedback de Moodle...")
        
        try:
            todos_los_datos = []
            total_actividades = len(actividades_faltantes)
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for contador, row in enumerate(actividades_faltantes):
                course_id = row['id_curso']
                assignment_id = row['id']
                assignment_name = row['name']
                course_name = row['NomCurso']
                docente = row['DOCENTE']
                
                status_text.text(f"Procesando con feedback: {assignment_name} ({contador + 1}/{total_actividades})")
                
                try:
                    grades_dict = obtener_grades(assignment_id)
                    participantes = obtener_ids_participantes(assignment_id)
                    
                    for p in participantes:
                        uid = p["id"]
                        fullname = p["fullname"]
                        grade = grades_dict.get(uid, "")
                        feedback = obtener_feedback(assignment_id, uid)
                        
                        todos_los_datos.append({
                            "course_id": course_id,
                            "course_name": course_name,
                            "docente": docente,
                            "assignment_id": assignment_id,
                            "assignment_name": assignment_name,
                            "user_id": uid,
                            "user_fullname": fullname,
                            "grade": grade,
                            "feedback": feedback,
                            "has_feedback": len(str(feedback).strip()) > 0
                        })
                    
                    time.sleep(0.1)
                    
                except Exception as e:
                    st.warning(f"Error procesando {assignment_name}: {str(e)}")
                    continue
                
                progreso = min((contador + 1) / total_actividades, 1.0)
                progress_bar.progress(progreso)
            
            status_text.empty()
            progress_bar.empty()
            
            df_nuevos = pd.DataFrame(todos_los_datos)
            
            if not df_nuevos.empty:
                # Guardar en Supabase
                exito_supabase, registros_guardados = guardar_datos_en_supabase(todos_los_datos)
                if exito_supabase:
                    st.success(f"💾 {registros_guardados} registros con feedback guardados en Supabase")
                
                # Combinar con datos existentes
                if not df_supabase.empty:
                    df_final = pd.concat([df_supabase, df_nuevos], ignore_index=True)
                else:
                    df_final = df_nuevos
                
                # Guardar en cache
                guardar_en_cache_masivo(df_final.copy(), cache_key_feedback)
                
                st.success(f"✅ Extracción con feedback completada: {len(df_final)} registros totales")
                return df_final
            
        except Exception as e:
            st.error(f"Error al extraer datos con feedback: {str(e)}")
    
    # Retornar datos de Supabase si no hay actividades faltantes
    if not df_supabase.empty:
        st.success(f"✅ Todos los datos con feedback obtenidos de Supabase: {len(df_supabase)} registros")
        return df_supabase
    
    st.warning("No se pudieron obtener datos con feedback.")
    return pd.DataFrame()

# ==========================
# FUNCIONES DE FILTRADO
# ==========================
def aplicar_filtros(df, filtro_feedback, filtro_calificacion, valor_calificacion):
    """Aplica filtros al dataframe"""
    df_filtrado = df.copy()
    
    if filtro_feedback == "Sin feedback":
        df_filtrado = df_filtrado[~df_filtrado['has_feedback']]
    elif filtro_feedback == "Con feedback":
        df_filtrado = df_filtrado[df_filtrado['has_feedback']]
    
    if filtro_calificacion != "Todas":
        if filtro_calificacion == "Igual a":
            df_filtrado = df_filtrado[df_filtrado['grade'] == valor_calificacion]
        elif filtro_calificacion == "Mayor a":
            df_filtrado = df_filtrado[pd.to_numeric(df_filtrado['grade'], errors='coerce') > valor_calificacion]
        elif filtro_calificacion == "Menor a":
            df_filtrado = df_filtrado[pd.to_numeric(df_filtrado['grade'], errors='coerce') < valor_calificacion]
        elif filtro_calificacion == "Sin calificar":
            df_filtrado = df_filtrado[df_filtrado['grade'].isin(['', '-', 0, '0'])]
    
    return df_filtrado

def aplicar_filtros_casos_especiales(df, tipo_caso, actividades_seleccionadas=None):
    """Aplica filtros para casos especiales de análisis"""
    df_filtrado = df.copy()
    
    if tipo_caso == "Calificación 16-18 sin feedback":
        # Convertir grades a numérico
        df_filtrado['grade_numeric'] = pd.to_numeric(df_filtrado['grade'], errors='coerce')
        df_filtrado = df_filtrado[
            (df_filtrado['grade_numeric'] >= 16) & 
            (df_filtrado['grade_numeric'] <= 18) & 
            (~df_filtrado['has_feedback'])
        ]
    
    elif tipo_caso == "Calificación 14-15 sin feedback":
        df_filtrado['grade_numeric'] = pd.to_numeric(df_filtrado['grade'], errors='coerce')
        df_filtrado = df_filtrado[
            (df_filtrado['grade_numeric'] >= 14) & 
            (df_filtrado['grade_numeric'] <= 15) & 
            (~df_filtrado['has_feedback'])
        ]
    
    elif tipo_caso == "Calificación 1-13 sin feedback":
        df_filtrado['grade_numeric'] = pd.to_numeric(df_filtrado['grade'], errors='coerce')
        df_filtrado = df_filtrado[
            (df_filtrado['grade_numeric'] >= 1) & 
            (df_filtrado['grade_numeric'] <= 13) & 
            (~df_filtrado['has_feedback'])
        ]
    
    elif tipo_caso == "Sin calificación en actividades específicas":
        if actividades_seleccionadas:
            # DEBUG: Agregar información de debug temporal
            print(f"DEBUG - Actividades recibidas: {actividades_seleccionadas}")
            print(f"DEBUG - Actividades únicas en datos: {df_filtrado['assignment_name'].unique()}")
            print(f"DEBUG - Total registros antes de filtrar: {len(df_filtrado)}")
            
            # Filtrar primero por actividades específicas
            df_actividades_especificas = df_filtrado[df_filtrado['assignment_name'].isin(actividades_seleccionadas)]
            print(f"DEBUG - Registros después de filtrar por actividades: {len(df_actividades_especificas)}")
            
            if len(df_actividades_especificas) > 0:
                # Mostrar algunas calificaciones de ejemplo
                print(f"DEBUG - Ejemplos de calificaciones: {df_actividades_especificas['grade'].head(10).tolist()}")
                
                # Convertir grades a numérico para evaluación más precisa
                df_actividades_especificas['grade_numeric'] = pd.to_numeric(df_actividades_especificas['grade'], errors='coerce')
                
                # Considerar "sin calificación" cuando:
                # - La calificación es NaN (valores no numéricos, vacíos, None)
                # - La calificación es exactamente 0
                # - La calificación es string vacío o guión
                sin_calificacion_mask = (
                    df_actividades_especificas['grade_numeric'].isna() |  # NaN (vacíos, None, strings no numéricos)
                    (df_actividades_especificas['grade_numeric'] == 0) |  # Exactamente 0
                    (df_actividades_especificas['grade'].astype(str).str.strip().isin(['', '-', 'nan', 'None']))  # Strings vacíos o guiones
                )
                
                print(f"DEBUG - Registros que cumplen criterio sin calificación: {sin_calificacion_mask.sum()}")
                
                df_filtrado = df_actividades_especificas[sin_calificacion_mask]
            else:
                df_filtrado = pd.DataFrame()
        else:
            # Si no hay actividades seleccionadas, mostrar mensaje de error
            return pd.DataFrame()  # Retornar DataFrame vacío
    
    return df_filtrado

def ordenar_columnas_evaluacion_integral(df):
    """Ordena las columnas poniendo 'Evaluación Integral' al final"""
    if df.empty:
        return df
    
    columnas = list(df.columns)
    columnas_eval_integral = [col for col in columnas if 'evaluaci' in col.lower() and 'integral' in col.lower()]
    otras_columnas = [col for col in columnas if col not in columnas_eval_integral]
    
    # Reorganizar: otras columnas primero, luego Evaluación Integral
    columnas_ordenadas = otras_columnas + columnas_eval_integral
    
    return df[columnas_ordenadas]

# ==========================
# PESTAÑA 1: EXTRACCIÓN INDIVIDUAL
# ==========================
def mostrar_pestana_individual():
    st.header("📋 Extracción Individual de Actividades")
    st.markdown("Extrae calificaciones y feedback de una actividad específica")
    
    # Cargar datos
    if not os.path.exists(ASIGNACIONES_CSV) or not os.path.exists(CURSOS_CSV):
        st.error("❌ No se encontraron los archivos CSV necesarios (asignaciones_evaluaciones.csv, cursos.csv)")
        return
    
    try:
        df_asignaciones = pd.read_csv(ASIGNACIONES_CSV)
        df_cursos = pd.read_csv(CURSOS_CSV)
        
        # Cargar datos de enlaces de aulas si existe el archivo
        df_aulas_enlaces = pd.DataFrame()
        if os.path.exists("aulas_enlaces.csv"):
            df_aulas_enlaces = pd.read_csv("aulas_enlaces.csv")
            st.sidebar.success("🔗 Enlaces de aulas cargados")
        else:
            st.sidebar.warning("⚠️ Archivo aulas_enlaces.csv no encontrado")
            
    except Exception as e:
        st.error(f"Error al cargar los archivos CSV: {str(e)}")
        return
    
    # Combinar datos
    df_combinado = df_asignaciones.merge(
        df_cursos[['id_NRC', 'NomCurso', 'DOCENTE', 'Modalidad', 'NRC']], 
        left_on='id_curso', 
        right_on='id_NRC', 
        how='left'
    )
    
    # Sidebar para filtros de selección - FILTROS CONDICIONALES CON SELECTBOX
    st.sidebar.header("🔍 Filtros de Selección")
    st.sidebar.markdown("*Filtros condicionales: Modalidad → Cursos → Docentes*")
    
    # FILTRO DOMINANTE 1: MODALIDADES (SelectBox con opción "Todos")
    modalidades_disponibles = ["Todos"] + sorted(df_combinado['Modalidad'].dropna().unique().tolist())
    modalidad_seleccionada = st.sidebar.selectbox(
        "1️⃣ Seleccionar Modalidad:",
        modalidades_disponibles,
        index=0,  # Por defecto "Todos"
        help="Filtro principal - determina qué cursos y docentes aparecen",
        key="modalidad_individual"
    )
    
    # Filtrar datos por modalidad seleccionada
    if modalidad_seleccionada == "Todos":
        df_filtrado_modalidad = df_combinado.copy()
    else:
        df_filtrado_modalidad = df_combinado[df_combinado['Modalidad'] == modalidad_seleccionada]
    
    # FILTRO CONDICIONAL 2: CURSOS (solo los de la modalidad seleccionada)
    cursos_disponibles = ["Todos"] + sorted(df_filtrado_modalidad['NomCurso'].dropna().unique().tolist())
    curso_seleccionado = st.sidebar.selectbox(
        "2️⃣ Seleccionar Curso:",
        cursos_disponibles,
        index=0,  # Por defecto "Todos"
        help="Solo cursos de la modalidad seleccionada",
        key="curso_individual"
    )
    
    # Filtrar por curso seleccionado
    if curso_seleccionado == "Todos":
        df_filtrado_curso = df_filtrado_modalidad.copy()
    else:
        df_filtrado_curso = df_filtrado_modalidad[df_filtrado_modalidad['NomCurso'] == curso_seleccionado]
    
    # FILTRO CONDICIONAL 3: DOCENTES (solo los que enseñan en los cursos y modalidad seleccionadas)
    docentes_disponibles = ["Todos"] + sorted(df_filtrado_curso['DOCENTE'].dropna().unique().tolist())
    docente_seleccionado = st.sidebar.selectbox(
        "3️⃣ Seleccionar Docente:",
        docentes_disponibles,
        index=0,  # Por defecto "Todos"
        help="Solo docentes que enseñan en los cursos y modalidad seleccionadas",
        key="docente_individual"
    )
    
    # Filtrar por docente seleccionado
    if docente_seleccionado == "Todos":
        df_filtrado = df_filtrado_curso.copy()
    else:
        df_filtrado = df_filtrado_curso[df_filtrado_curso['DOCENTE'] == docente_seleccionado]
    
    # Mostrar información de filtros aplicados
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Resumen de Filtros")
    st.sidebar.info(f"**Modalidad:** {modalidad_seleccionada}")
    st.sidebar.info(f"**Curso:** {curso_seleccionado}")
    st.sidebar.info(f"**Docente:** {docente_seleccionado}")
    st.sidebar.info(f"**Actividades disponibles:** {len(df_filtrado)}")
    
    # Botón para resetear filtros
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Resetear Filtros", help="Vuelve todos los filtros a 'Todos'", type="secondary"):
        # Limpiar las claves específicas de los filtros
        keys_to_clear = [
            "modalidad_individual", 
            "curso_individual", 
            "docente_individual"
        ]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()
    
    # Mostrar actividades disponibles
    st.subheader("📋 Actividades Disponibles")
    
    if df_filtrado.empty:
        st.warning("No se encontraron actividades con los filtros seleccionados.")
        st.info("💡 **Sugerencia:** Ajusta los filtros en la barra lateral para ver actividades disponibles.")
        return
    
    # Selector de actividad
    actividades_info = []
    for _, row in df_filtrado.iterrows():
        info = f"{row['NomCurso']} - {row['name']} (Docente: {row['DOCENTE']}, Modalidad: {row['Modalidad']})" 
        actividades_info.append((info, row))
    
    actividad_seleccionada = st.selectbox(
        "Seleccionar Actividad:",
        range(len(actividades_info)),
        format_func=lambda x: actividades_info[x][0],
        key="individual_actividad"
    )
    
    if actividad_seleccionada is not None and actividades_info:
        row_seleccionada = actividades_info[actividad_seleccionada][1]
        
        # Mostrar información de la actividad seleccionada
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.info(f"**Curso:** {row_seleccionada['NomCurso']}")
        with col2:
            st.info(f"**Actividad:** {row_seleccionada['name']}")
        with col3:
            st.info(f"**Docente:** {row_seleccionada['DOCENTE']}")
        with col4:
            st.info(f"**Modalidad:** {row_seleccionada['Modalidad']}")
        
        # Mostrar enlace al aula si está disponible
        if not df_aulas_enlaces.empty and 'NRC' in row_seleccionada and pd.notna(row_seleccionada['NRC']):
            nrc_actividad = row_seleccionada['NRC']
            enlace_aula = df_aulas_enlaces[df_aulas_enlaces['NRC'] == nrc_actividad]
            
            if not enlace_aula.empty:
                url_aula = enlace_aula.iloc[0]['url']
                st.markdown("---")
                st.markdown(f"### 🏫 **Acceso Directo al Aula**")
                st.markdown(f"**NRC:** {nrc_actividad}")
                st.markdown(f"🔗 **[Ir al Aula Virtual]({url_aula})**", unsafe_allow_html=True)
                
                # Botón adicional más visible
                if st.button("🚀 **Abrir Aula Virtual**", type="secondary", help=f"Abre el aula NRC {nrc_actividad} en una nueva pestaña"):
                    st.markdown(f'<meta http-equiv="refresh" content="0; URL={url_aula}" target="_blank">', unsafe_allow_html=True)
                    st.balloons()
        
        st.markdown("---")
        
        # Botón para extraer datos
        if st.button("🚀 Extraer Calificaciones y Feedback", type="primary"):
            with st.spinner("Extrayendo datos..."):
                df_resultados = extraer_calificaciones_feedback(
                    row_seleccionada['id_curso'],
                    row_seleccionada['id'],
                    row_seleccionada['name'],
                    row_seleccionada['NomCurso'],
                    row_seleccionada['DOCENTE']
                )
                
                if not df_resultados.empty:
                    st.session_state['df_resultados_individual'] = df_resultados
                    st.session_state['row_seleccionada'] = row_seleccionada  # Guardar para mostrar enlace en resultados
                    st.success("¡Datos extraídos exitosamente!")
    
    # Mostrar resultados si existen
    if 'df_resultados_individual' in st.session_state and not st.session_state['df_resultados_individual'].empty:
        st.markdown("---")
        st.subheader("📊 Resultados")
        
        df_resultados = st.session_state['df_resultados_individual']
        
        # Mostrar enlace al aula en la sección de resultados también
        if 'row_seleccionada' in st.session_state and not df_aulas_enlaces.empty:
            row_resultado = st.session_state['row_seleccionada']
            if 'NRC' in row_resultado and pd.notna(row_resultado['NRC']):
                nrc_resultado = row_resultado['NRC']
                enlace_resultado = df_aulas_enlaces[df_aulas_enlaces['NRC'] == nrc_resultado]
                
                if not enlace_resultado.empty:
                    url_resultado = enlace_resultado.iloc[0]['url']
                    
                    # Panel destacado para el enlace al aula
                    st.success(f"🏫 **Aula Virtual - NRC {nrc_resultado}**")
                    col_enlace1, col_enlace2 = st.columns([3, 1])
                    with col_enlace1:
                        st.markdown(f"**Acceso directo:** [🔗 Ir al Aula Virtual]({url_resultado})")
                    with col_enlace2:
                        if st.button("🚀 Abrir Aula", key="abrir_aula_resultados"):
                            st.markdown(f'<script>window.open("{url_resultado}", "_blank");</script>', unsafe_allow_html=True)
        
        # Filtros de resultados
        st.subheader("🔧 Filtros de Resultados")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            filtro_feedback = st.selectbox(
                "Filtro de Feedback:",
                ["Todos", "Con feedback", "Sin feedback"],
                key="feedback_individual"
            )
        
        with col2:
            filtro_calificacion = st.selectbox(
                "Filtro de Calificación:",
                ["Todas", "Igual a", "Mayor a", "Menor a", "Sin calificar"],
                key="calificacion_individual"
            )
        
        with col3:
            valor_calificacion = st.number_input(
                "Valor de Calificación:",
                min_value=0,
                max_value=20,
                value=10,
                disabled=(filtro_calificacion in ["Todas", "Sin calificar"]),
                key="valor_individual"
            )
        
        # Aplicar filtros
        df_mostrar = aplicar_filtros(df_resultados, filtro_feedback, filtro_calificacion, valor_calificacion)
        
        # Estadísticas
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Estudiantes", len(df_resultados))
        with col2:
            st.metric("Con Feedback", len(df_resultados[df_resultados['has_feedback']]))
        with col3:
            st.metric("Sin Feedback", len(df_resultados[~df_resultados['has_feedback']]))
        with col4:
            st.metric("Filtrados", len(df_mostrar))
        
        # Mostrar tabla de resultados
        st.subheader("📋 Tabla de Resultados")
        st.dataframe(
            df_mostrar[['user_fullname', 'grade', 'has_feedback', 'feedback']].rename(columns={
                'user_fullname': 'Estudiante',
                'grade': 'Calificación', 
                'has_feedback': 'Tiene Feedback',
                'feedback': 'Feedback'
            }),
            use_container_width=True,
            height=400
        )
        
        # Botón de descarga
        csv = df_mostrar.to_csv(index=False)
        nombre_archivo = f"calificaciones_{row_seleccionada['NomCurso'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        st.download_button(
            label="📥 Descargar Resultados (CSV)",
            data=csv,
            file_name=nombre_archivo,
            mime="text/csv"
        )

# ==========================
# PESTAÑA 2: EXTRACCIÓN MASIVA
# ==========================
def mostrar_pestana_masiva():
    st.header("📊 Extracción Masiva de Calificaciones")
    st.markdown("Extrae calificaciones de múltiples actividades y muestra en formato matriz")
    
    # Cargar datos
    if not os.path.exists(ASIGNACIONES_CSV) or not os.path.exists(CURSOS_CSV):
        st.error("❌ No se encontraron los archivos CSV necesarios")
        return
    
    try:
        df_asignaciones = pd.read_csv(ASIGNACIONES_CSV)
        df_cursos = pd.read_csv(CURSOS_CSV)
        
        # Cargar datos de enlaces de aulas
        df_aulas_enlaces = pd.DataFrame()
        if os.path.exists("aulas_enlaces.csv"):
            df_aulas_enlaces = pd.read_csv("aulas_enlaces.csv")
        
    except Exception as e:
        st.error(f"Error al cargar los archivos CSV: {str(e)}")
        return
    
    # Combinar datos
    df_combinado = df_asignaciones.merge(
        df_cursos[['id_NRC', 'NomCurso', 'DOCENTE', 'Modalidad', 'NRC']], 
        left_on='id_curso', 
        right_on='id_NRC', 
        how='left'
    )
    
    # Selector de tipo de extracción
    st.subheader("🎯 Tipo de Extracción Masiva")
    tipo_extraccion = st.selectbox(
        "Seleccionar tipo de extracción:",
        [
            "Todas las aulas de un curso",
            "Todas las aulas de un profesor", 
            "Todas las actividades de un aula"
        ],
        key="masiva_tipo_extraccion"
    )
    
    actividades_seleccionadas = pd.DataFrame()
    identificador = ""
    
    if tipo_extraccion == "Todas las aulas de un curso":
        cursos_disponibles = sorted(df_combinado['NomCurso'].dropna().unique())
        curso_seleccionado = st.selectbox("Seleccionar Curso:", cursos_disponibles, key="masiva_curso")
        
        if curso_seleccionado:
            actividades_seleccionadas = df_combinado[df_combinado['NomCurso'] == curso_seleccionado]
            identificador = f"curso_{curso_seleccionado}"
            st.info(f"📋 Se extraerán {len(actividades_seleccionadas)} actividades del curso: **{curso_seleccionado}**")
    
    elif tipo_extraccion == "Todas las aulas de un profesor":
        docentes_disponibles = sorted(df_combinado['DOCENTE'].dropna().unique())
        docente_seleccionado = st.selectbox("Seleccionar Profesor:", docentes_disponibles, key="masiva_docente")
        
        if docente_seleccionado:
            actividades_seleccionadas = df_combinado[df_combinado['DOCENTE'] == docente_seleccionado]
            identificador = f"docente_{docente_seleccionado}"
            st.info(f"📋 Se extraerán {len(actividades_seleccionadas)} actividades del profesor: **{docente_seleccionado}**")
    
    elif tipo_extraccion == "Todas las actividades de un aula":
        # Crear identificador único para cada aula (NRC ya está disponible en df_combinado)
        df_combinado['aula_id'] = df_combinado['NRC'].fillna('SIN_NRC').astype(str) + ' - ' + df_combinado['NomCurso'].astype(str) + ' - ' + df_combinado['DOCENTE'].astype(str)
        aulas_disponibles = sorted(df_combinado['aula_id'].dropna().unique())
        aula_seleccionada = st.selectbox("Seleccionar Aula:", aulas_disponibles, key="masiva_aula")
        
        if aula_seleccionada:
            actividades_seleccionadas = df_combinado[df_combinado['aula_id'] == aula_seleccionada]
            identificador = f"aula_{aula_seleccionada}"
            st.info(f"📋 Se extraerán {len(actividades_seleccionadas)} actividades del aula: **{aula_seleccionada}**")
    
    # Mostrar preview de actividades
    if not actividades_seleccionadas.empty:
        with st.expander("👁️ Ver actividades seleccionadas"):
            st.dataframe(
                actividades_seleccionadas[['NomCurso', 'name', 'DOCENTE', 'Modalidad']].rename(columns={
                    'NomCurso': 'Curso',
                    'name': 'Actividad',
                    'DOCENTE': 'Docente',
                    'Modalidad': 'Modalidad'
                }),
                use_container_width=True
            )
        
        # Botón para extraer datos masivos
        if st.button("🚀 Extraer Calificaciones Masivas", type="primary"):
            with st.spinner("Extrayendo datos masivos... Esto puede tomar varios minutos."):
                df_masivo = extraer_calificaciones_masivo(actividades_seleccionadas, identificador)
                
                if not df_masivo.empty:
                    st.session_state['df_masivo'] = df_masivo
                    st.session_state['tipo_extraccion'] = tipo_extraccion
                    st.success("¡Datos masivos extraídos exitosamente!")
    
    # Mostrar resultados masivos si existen
    if 'df_masivo' in st.session_state and not st.session_state['df_masivo'].empty:
        st.markdown("---")
        st.subheader("📊 Resultados Masivos")
        
        df_masivo = st.session_state['df_masivo']
        
        # Crear matriz de calificaciones
        matriz_calificaciones = crear_matriz_calificaciones(df_masivo)
        
        if not matriz_calificaciones.empty:
            # Estadísticas
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Estudiantes", len(matriz_calificaciones))
            with col2:
                st.metric("Total Actividades", len(matriz_calificaciones.columns) - 3)  # -3 por las columnas de info
            with col3:
                st.metric("Total Registros", len(df_masivo))
            
            # Filtros para la matriz
            st.subheader("🔧 Filtros de Matriz")
            col1, col2 = st.columns(2)
            
            with col1:
                # Filtro por curso (si aplica)
                if 'course_name' in matriz_calificaciones.columns:
                    cursos_en_matriz = sorted(matriz_calificaciones['course_name'].unique())
                    cursos_filtro = st.multiselect(
                        "Filtrar por Cursos:",
                        cursos_en_matriz,
                        default=cursos_en_matriz,
                        key="cursos_matriz"
                    )
                else:
                    cursos_filtro = []
            
            with col2:
                # Filtro por docente (si aplica)
                if 'docente' in matriz_calificaciones.columns:
                    docentes_en_matriz = sorted(matriz_calificaciones['docente'].unique())
                    docentes_filtro = st.multiselect(
                        "Filtrar por Docentes:",
                        docentes_en_matriz,
                        default=docentes_en_matriz,
                        key="docentes_matriz"
                    )
                else:
                    docentes_filtro = []
            
            # Aplicar filtros a la matriz
            matriz_filtrada = matriz_calificaciones.copy()
            
            if cursos_filtro and 'course_name' in matriz_calificaciones.columns:
                matriz_filtrada = matriz_filtrada[matriz_filtrada['course_name'].isin(cursos_filtro)]
            
            if docentes_filtro and 'docente' in matriz_calificaciones.columns:
                matriz_filtrada = matriz_filtrada[matriz_filtrada['docente'].isin(docentes_filtro)]
            
            # Mostrar matriz
            st.subheader("📋 Matriz de Calificaciones")
            st.markdown("*Filas: Estudiantes | Columnas: Actividades*")
            
            if not matriz_filtrada.empty:
                # Configurar el ancho de columnas
                st.dataframe(
                    matriz_filtrada,
                    use_container_width=True,
                    height=400
                )
                
                # Botones de descarga
                col1, col2 = st.columns(2)
                with col1:
                    csv_matriz = matriz_filtrada.to_csv(index=False)
                    st.download_button(
                        label="📥 Descargar Matriz (CSV)",
                        data=csv_matriz,
                        file_name=f"matriz_calificaciones_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                
                with col2:
                    csv_datos_completos = df_masivo.to_csv(index=False)
                    st.download_button(
                        label="📥 Descargar Datos Completos (CSV)",
                        data=csv_datos_completos,
                        file_name=f"datos_masivos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
            else:
                st.warning("No hay datos que mostrar con los filtros aplicados.")
        else:
            st.warning("No se pudo crear la matriz de calificaciones.")

# ==========================
# PESTAÑA 3: ANÁLISIS DE CASOS ESPECIALES
# ==========================
def mostrar_pestana_casos_especiales():
    st.header("🔍 Análisis de Casos Especiales")
    st.markdown("Análisis específico de estudiantes según criterios de calificación y feedback")
    
    # Cargar datos
    if not os.path.exists(ASIGNACIONES_CSV) or not os.path.exists(CURSOS_CSV):
        st.error("❌ No se encontraron los archivos CSV necesarios")
        return
    
    try:
        df_asignaciones = pd.read_csv(ASIGNACIONES_CSV)
        df_cursos = pd.read_csv(CURSOS_CSV)
        
        # Cargar datos de enlaces de aulas
        df_aulas_enlaces = pd.DataFrame()
        if os.path.exists("aulas_enlaces.csv"):
            df_aulas_enlaces = pd.read_csv("aulas_enlaces.csv")
        
    except Exception as e:
        st.error(f"Error al cargar los archivos CSV: {str(e)}")
        return
    
    # Combinar datos
    df_combinado = df_asignaciones.merge(
        df_cursos[['id_NRC', 'NomCurso', 'DOCENTE', 'Modalidad', 'NRC']], 
        left_on='id_curso', 
        right_on='id_NRC', 
        how='left'
    )
    
    # Selector de tipo de consulta
    st.subheader("🎯 Tipo de Consulta")
    tipo_consulta = st.selectbox(
        "Seleccionar tipo de consulta:",
        [
            "Por aula específica (curso + docente)",
            "Todas las aulas de un curso",
            "Todas las aulas de un profesor"
        ],
        key="casos_tipo_consulta"
    )
    
    actividades_seleccionadas = pd.DataFrame()
    identificador = ""
    
    if tipo_consulta == "Por aula específica (curso + docente)":
        # Crear identificador único para cada aula (NRC ya está disponible en df_combinado)
        df_combinado['aula_id'] = df_combinado['NRC'].fillna('SIN_NRC').astype(str) + ' - ' + df_combinado['NomCurso'].astype(str) + ' - ' + df_combinado['DOCENTE'].astype(str)
        aulas_disponibles = sorted(df_combinado['aula_id'].dropna().unique())
        aula_seleccionada = st.selectbox("Seleccionar Aula:", aulas_disponibles, key="casos_aula")
        
        if aula_seleccionada:
            actividades_seleccionadas = df_combinado[df_combinado['aula_id'] == aula_seleccionada]
            identificador = f"casos_aula_{aula_seleccionada}"
    
    elif tipo_consulta == "Todas las aulas de un curso":
        cursos_disponibles = sorted(df_combinado['NomCurso'].dropna().unique())
        curso_seleccionado = st.selectbox("Seleccionar Curso:", cursos_disponibles, key="casos_curso")
        
        if curso_seleccionado:
            actividades_seleccionadas = df_combinado[df_combinado['NomCurso'] == curso_seleccionado]
            identificador = f"casos_curso_{curso_seleccionado}"
    
    elif tipo_consulta == "Todas las aulas de un profesor":
        docentes_disponibles = sorted(df_combinado['DOCENTE'].dropna().unique())
        docente_seleccionado = st.selectbox("Seleccionar Profesor:", docentes_disponibles, key="casos_docente")
        
        if docente_seleccionado:
            actividades_seleccionadas = df_combinado[df_combinado['DOCENTE'] == docente_seleccionado]
            identificador = f"casos_docente_{docente_seleccionado}"
    
    # Selector de caso especial
    st.subheader("📋 Caso Especial a Analizar")
    caso_especial = st.selectbox(
        "Seleccionar caso especial:",
        [
            "Calificación 16-18 sin feedback",
            "Calificación 14-15 sin feedback", 
            "Calificación 1-13 sin feedback",
            "Sin calificación en actividades específicas"
        ],
        key="casos_especial"
    )
    
    # Selector de actividades específicas para el caso 4
    actividades_para_analizar = []
    if caso_especial == "Sin calificación en actividades específicas" and not actividades_seleccionadas.empty:
        st.subheader("🎯 Actividades a Analizar")
        st.markdown("*Selecciona las actividades específicas donde buscar estudiantes sin calificación:*")
        
        actividades_disponibles = sorted(actividades_seleccionadas['name'].unique())
        
        # Inicializar estado de checkboxes si no existe
        if 'checkbox_states' not in st.session_state:
            st.session_state.checkbox_states = {}
        
        # Botones de selección rápida
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("✅ Seleccionar Todas", key="select_all_activities"):
                for i, actividad in enumerate(actividades_disponibles):
                    st.session_state.checkbox_states[f"check_actividad_{i}"] = True
                st.rerun()
        with col_b:
            if st.button("❌ Deseleccionar Todas", key="deselect_all_activities"):
                for i, actividad in enumerate(actividades_disponibles):
                    st.session_state.checkbox_states[f"check_actividad_{i}"] = False
                st.rerun()
        
        # Crear checkboxes para cada actividad
        col1, col2 = st.columns(2)
        actividades_para_analizar = []
        
        for i, actividad in enumerate(actividades_disponibles):
            checkbox_key = f"check_actividad_{i}"
            
            # Alternar entre columnas
            with col1 if i % 2 == 0 else col2:
                # Usar el valor actual del checkbox desde session_state
                checkbox_checked = st.checkbox(
                    actividad, 
                    key=checkbox_key, 
                    value=st.session_state.checkbox_states.get(checkbox_key, False)
                )
                
                if checkbox_checked:
                    actividades_para_analizar.append(actividad)
                    
                # Actualizar el estado
                st.session_state.checkbox_states[checkbox_key] = checkbox_checked
        
        with col_c:
            st.info(f"📋 {len(actividades_para_analizar)} actividades seleccionadas")
        
        if len(actividades_para_analizar) == 0:
            st.warning("⚠️ Debes seleccionar al menos una actividad para analizar.")
    
    # Preview de actividades
    if not actividades_seleccionadas.empty:
        # Mostrar información diferente según el caso especial
        if caso_especial == "Sin calificación en actividades específicas":
            if len(actividades_para_analizar) > 0:
                st.success(f"🎯 Se buscará en {len(actividades_para_analizar)} actividades específicas: {', '.join(actividades_para_analizar)}")
            else:
                st.warning("⚠️ Selecciona al menos una actividad específica para analizar")
        else:
            st.info(f"📋 Se analizarán {len(actividades_seleccionadas)} actividades disponibles")
        
        with st.expander("👁️ Ver todas las actividades disponibles"):
            st.dataframe(
                actividades_seleccionadas[['NomCurso', 'name', 'DOCENTE', 'Modalidad']].rename(columns={
                    'NomCurso': 'Curso',
                    'name': 'Actividad',
                    'DOCENTE': 'Docente',
                    'Modalidad': 'Modalidad'
                }),
                use_container_width=True
            )
        
        # Botón para extraer datos
        boton_habilitado = True
        if caso_especial == "Sin calificación en actividades específicas" and len(actividades_para_analizar) == 0:
            boton_habilitado = False
        
        if st.button("🚀 Extraer y Analizar Casos Especiales", type="primary", disabled=not boton_habilitado):
            with st.spinner("Extrayendo datos para análisis... Esto puede tomar varios minutos."):
                df_casos = extraer_datos_con_feedback(actividades_seleccionadas, identificador)
                
                if not df_casos.empty:
                    st.session_state['df_casos'] = df_casos
                    st.session_state['caso_especial'] = caso_especial
                    st.session_state['actividades_para_analizar'] = actividades_para_analizar
                    st.success("¡Datos extraídos exitosamente para análisis!")
                    st.info(f"🎯 Analizando caso: **{caso_especial}**")
                    if actividades_para_analizar:
                        st.info(f"📋 Actividades específicas seleccionadas: {', '.join(actividades_para_analizar)}")
                    
                    # Debug: Mostrar información de lo que se guardó
                    st.info(f"🔍 Debug - Total actividades extraídas: {len(df_casos)}")
                    st.info(f"🔍 Debug - Actividades únicas en datos: {', '.join(df_casos['assignment_name'].unique())}")
        
        if not boton_habilitado:
            st.error("❌ Debes seleccionar al menos una actividad antes de continuar.")
    
    # Mostrar análisis si existen datos
    if 'df_casos' in st.session_state and not st.session_state['df_casos'].empty:
        st.markdown("---")
        st.subheader("📊 Análisis de Casos Especiales")
        
        df_casos = st.session_state['df_casos']
        caso_actual = st.session_state.get('caso_especial', caso_especial)
        actividades_analizar = st.session_state.get('actividades_para_analizar', actividades_para_analizar)
        
        # Debug: Mostrar información antes del filtrado
        st.info(f"🔍 Debug - Caso actual: {caso_actual}")
        st.info(f"🔍 Debug - Actividades para analizar: {actividades_analizar}")
        
        # Aplicar filtro de caso especial
        df_filtrado = aplicar_filtros_casos_especiales(df_casos, caso_actual, actividades_analizar)
        
        # Debug: Mostrar información después del filtrado
        if not df_filtrado.empty:
            st.info(f"🔍 Debug - Actividades en resultados filtrados: {', '.join(df_filtrado['assignment_name'].unique())}")
        else:
            st.info("🔍 Debug - No hay resultados después del filtrado")
        
        if not df_filtrado.empty:
            # Estadísticas del caso
            st.subheader("📈 Estadísticas del Caso")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Registros", len(df_casos))
            with col2:
                st.metric("Casos Encontrados", len(df_filtrado))
            with col3:
                estudiantes_unicos = df_filtrado['user_fullname'].nunique()
                st.metric("Estudiantes Únicos", estudiantes_unicos)
            with col4:
                actividades_unicas = df_filtrado['assignment_name'].nunique()
                st.metric("Actividades Afectadas", actividades_unicas)
            
            # Mostrar casos en formato tabla
            st.subheader("📋 Casos Encontrados")
            casos_tabla = df_filtrado[['user_fullname', 'course_name', 'docente', 'assignment_name', 'grade']].rename(columns={
                'user_fullname': 'Estudiante',
                'course_name': 'Curso',
                'docente': 'Docente',
                'assignment_name': 'Actividad',
                'grade': 'Calificación'
            })
            
            st.dataframe(casos_tabla, use_container_width=True, height=400)
            
            # Crear matriz de casos
            st.subheader("📊 Matriz de Casos")
            st.markdown("*Vista matricial de los casos encontrados*")
            
            # Crear matriz solo con los casos filtrados
            if len(df_filtrado) > 0:
                matriz_casos = df_filtrado.pivot_table(
                    index=['user_fullname', 'course_name', 'docente'],
                    columns='assignment_name',
                    values='grade',
                    aggfunc='first',
                    fill_value=''
                ).reset_index()
                
                # Ordenar columnas poniendo Evaluación Integral al final
                matriz_casos = ordenar_columnas_evaluacion_integral(matriz_casos)
                
                st.dataframe(matriz_casos, use_container_width=True, height=400)
                
                # Botones de descarga
                col1, col2 = st.columns(2)
                with col1:
                    csv_casos = casos_tabla.to_csv(index=False)
                    st.download_button(
                        label="📥 Descargar Casos (CSV)",
                        data=csv_casos,
                        file_name=f"casos_{caso_actual.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                
                with col2:
                    csv_matriz = matriz_casos.to_csv(index=False)
                    st.download_button(
                        label="📥 Descargar Matriz (CSV)", 
                        data=csv_matriz,
                        file_name=f"matriz_casos_{caso_actual.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
            
            # Análisis por estudiante
            if estudiantes_unicos > 0:
                st.subheader("👥 Análisis por Estudiante")
                casos_por_estudiante = df_filtrado.groupby('user_fullname').agg({
                    'assignment_name': 'count',
                    'course_name': 'first',
                    'docente': 'first'
                }).rename(columns={
                    'assignment_name': 'Cantidad_Casos'
                }).reset_index()
                
                casos_por_estudiante = casos_por_estudiante.rename(columns={
                    'user_fullname': 'Estudiante',
                    'course_name': 'Curso', 
                    'docente': 'Docente',
                    'Cantidad_Casos': 'Casos Encontrados'
                })
                
                st.dataframe(casos_por_estudiante, use_container_width=True)
        
        else:
            st.info(f"✅ No se encontraron casos del tipo: **{caso_actual}**")
            st.markdown("Esto puede ser una buena noticia, dependiendo del caso analizado.")
    
    # Información sobre los casos
    with st.expander("ℹ️ Información sobre los Casos Especiales"):
        st.markdown("""
        **📋 Descripción de los Casos:**
        
        1. **Calificación 16-18 sin feedback**: Estudiantes con buenas calificaciones que no recibieron retroalimentación específica
        
        2. **Calificación 14-15 sin feedback**: Estudiantes con calificaciones regulares que podrían beneficiarse de feedback
        
        3. **Calificación 1-13 sin feedback**: Estudiantes con calificaciones bajas que necesitan urgentemente retroalimentación
        
        4. **Sin calificación en actividades específicas**: Estudiantes que no han sido evaluados (calificación vacía o 0) en actividades particulares. Solo se consideran "con calificación" las notas de 1 a 20.
        
        **🎯 Objetivo:** Identificar estudiantes que requieren atención especial para mejorar el proceso de enseñanza-aprendizaje.
        """)

# ==========================
# PESTAÑA 4: BÚSQUEDA EN SUPABASE
# ==========================
def mostrar_pestana_busqueda_supabase():
    st.header("🔍 Búsqueda Avanzada en Base de Datos")
    st.markdown("Realiza búsquedas específicas en la base de datos Supabase por diferentes criterios")
    
    # Verificar conexión a Supabase
    if not verificar_conexion_supabase():
        st.error("❌ **No hay conexión a Supabase**")
        st.warning("Esta pestaña requiere conexión a la base de datos Supabase para funcionar.")
        st.info("💡 **Solución:** Verifica tu conexión a internet y configuración de Supabase")
        return
    
    # Cargar datos de referencia para los filtros
    try:
        df_cursos = pd.read_csv(CURSOS_CSV) if os.path.exists(CURSOS_CSV) else pd.DataFrame()
        df_aulas_enlaces = pd.read_csv("aulas_enlaces.csv") if os.path.exists("aulas_enlaces.csv") else pd.DataFrame()
    except Exception as e:
        st.error(f"Error al cargar archivos de referencia: {str(e)}")
        df_cursos = pd.DataFrame()
        df_aulas_enlaces = pd.DataFrame()
    
    # Obtener datos únicos de Supabase para los filtros
    st.subheader("🎯 Filtros de Búsqueda")
    
    try:
        # Obtener datos únicos directamente de Supabase para filtros dinámicos
        response_all = supabase.table('calificaciones_feedback').select('course_name, docente, user_fullname').execute()
        df_supabase_ref = pd.DataFrame(response_all.data)
        
        if df_supabase_ref.empty:
            st.warning("⚠️ No hay datos en la base de datos Supabase para realizar búsquedas.")
            st.info("💡 **Sugerencia:** Extrae algunos datos primero desde las otras pestañas.")
            return
            
    except Exception as e:
        st.error(f"Error al obtener datos de referencia de Supabase: {str(e)}")
        return
    
    # Configurar filtros en columnas
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 📚 Filtros Académicos")
        
        # Filtro por Curso
        cursos_disponibles = ["Todos"] + sorted(df_supabase_ref['course_name'].dropna().unique().tolist())
        curso_busqueda = st.selectbox(
            "🎓 Curso:",
            cursos_disponibles,
            key="busqueda_curso",
            help="Filtrar por nombre del curso"
        )
        
        # Filtro por NRC (si hay datos de cursos disponibles)
        if not df_cursos.empty:
            nrcs_disponibles = ["Todos"] + sorted(df_cursos['NRC'].dropna().astype(str).unique().tolist())
            nrc_busqueda = st.selectbox(
                "🔢 NRC:",
                nrcs_disponibles,
                key="busqueda_nrc",
                help="Filtrar por código NRC del curso"
            )
        else:
            nrc_busqueda = "Todos"
            st.info("ℹ️ NRC no disponible (archivo cursos.csv no cargado)")
    
    with col2:
        st.markdown("#### 👥 Filtros de Personas")
        
        # Filtro por Profesor
        docentes_disponibles = ["Todos"] + sorted(df_supabase_ref['docente'].dropna().unique().tolist())
        profesor_busqueda = st.selectbox(
            "👨‍🏫 Profesor:",
            docentes_disponibles,
            key="busqueda_profesor",
            help="Filtrar por nombre del docente"
        )
        
        # Filtro por Estudiante
        estudiantes_disponibles = ["Todos"] + sorted(df_supabase_ref['user_fullname'].dropna().unique().tolist())
        estudiante_busqueda = st.selectbox(
            "👨‍🎓 Estudiante:",
            estudiantes_disponibles,
            key="busqueda_estudiante",
            help="Filtrar por nombre del estudiante"
        )
    
    # Filtros adicionales
    st.markdown("#### ⚙️ Filtros Adicionales")
    col3, col4, col5 = st.columns(3)
    
    with col3:
        filtro_feedback = st.selectbox(
            "💬 Estado de Feedback:",
            ["Todos", "Con feedback", "Sin feedback"],
            key="busqueda_feedback"
        )
    
    with col4:
        filtro_calificacion = st.selectbox(
            "📊 Tipo de Calificación:",
            ["Todas", "Con calificación", "Sin calificar", "Rango específico"],
            key="busqueda_calificacion"
        )
    
    with col5:
        if filtro_calificacion == "Rango específico":
            rango_min = st.number_input("Mín:", 0, 20, 0, key="busqueda_min")
            rango_max = st.number_input("Máx:", 0, 20, 20, key="busqueda_max")
        else:
            rango_min, rango_max = 0, 20
    
    # Botones de acción
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    with col_btn1:
        realizar_busqueda = st.button("🔍 Realizar Búsqueda", type="primary")
    
    with col_btn2:
        if st.button("🔄 Limpiar Filtros", type="secondary"):
            # Limpiar session state de filtros
            keys_to_clear = [
                "busqueda_curso", "busqueda_nrc", "busqueda_profesor", 
                "busqueda_estudiante", "busqueda_feedback", "busqueda_calificacion"
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    
    with col_btn3:
        contar_registros = st.button("📊 Contar Registros", help="Solo cuenta sin mostrar datos")
    
    # Mostrar resumen de filtros aplicados
    filtros_aplicados = []
    if curso_busqueda != "Todos":
        filtros_aplicados.append(f"Curso: {curso_busqueda}")
    if nrc_busqueda != "Todos":
        filtros_aplicados.append(f"NRC: {nrc_busqueda}")
    if profesor_busqueda != "Todos":
        filtros_aplicados.append(f"Profesor: {profesor_busqueda}")
    if estudiante_busqueda != "Todos":
        filtros_aplicados.append(f"Estudiante: {estudiante_busqueda}")
    if filtro_feedback != "Todos":
        filtros_aplicados.append(f"Feedback: {filtro_feedback}")
    if filtro_calificacion != "Todas":
        filtros_aplicados.append(f"Calificación: {filtro_calificacion}")
    
    if filtros_aplicados:
        st.info(f"📋 **Filtros activos:** {' | '.join(filtros_aplicados)}")
    else:
        st.info("📋 **Sin filtros aplicados** - se mostrarán todos los registros")
    
    # Realizar búsqueda
    if realizar_busqueda or contar_registros:
        with st.spinner("🔍 Realizando búsqueda en Supabase..."):
            try:
                # Construir query de Supabase
                query = supabase.table('calificaciones_feedback').select('*')
                
                # Aplicar filtros
                if curso_busqueda != "Todos":
                    query = query.eq('course_name', curso_busqueda)
                
                if profesor_busqueda != "Todos":
                    query = query.eq('docente', profesor_busqueda)
                
                if estudiante_busqueda != "Todos":
                    query = query.eq('user_fullname', estudiante_busqueda)
                
                # Filtro por NRC (requiere join con datos locales)
                response = query.execute()
                df_resultados = pd.DataFrame(response.data)
                
                if not df_resultados.empty and nrc_busqueda != "Todos" and not df_cursos.empty:
                    # Filtrar por NRC usando datos locales
                    cursos_nrc = df_cursos[df_cursos['NRC'].astype(str) == nrc_busqueda]['id_NRC'].tolist()
                    if cursos_nrc:
                        df_resultados = df_resultados[df_resultados['course_id'].isin(cursos_nrc)]
                
                # Aplicar filtros adicionales
                if not df_resultados.empty:
                    if filtro_feedback == "Con feedback":
                        df_resultados = df_resultados[df_resultados['has_feedback'] == True]
                    elif filtro_feedback == "Sin feedback":
                        df_resultados = df_resultados[df_resultados['has_feedback'] == False]
                    
                    if filtro_calificacion == "Con calificación":
                        df_resultados = df_resultados[
                            (df_resultados['grade'].notna()) & 
                            (df_resultados['grade'].astype(str).str.strip() != '') &
                            (df_resultados['grade'].astype(str).str.strip() != '0')
                        ]
                    elif filtro_calificacion == "Sin calificar":
                        df_resultados = df_resultados[
                            (df_resultados['grade'].isna()) | 
                            (df_resultados['grade'].astype(str).str.strip() == '') |
                            (df_resultados['grade'].astype(str).str.strip() == '0')
                        ]
                    elif filtro_calificacion == "Rango específico":
                        df_resultados['grade_numeric'] = pd.to_numeric(df_resultados['grade'], errors='coerce')
                        df_resultados = df_resultados[
                            (df_resultados['grade_numeric'] >= rango_min) & 
                            (df_resultados['grade_numeric'] <= rango_max)
                        ]
                
                # Mostrar resultados
                if contar_registros:
                    st.success(f"📊 **Total de registros encontrados:** {len(df_resultados):,}")
                    
                    if len(df_resultados) > 0:
                        # Estadísticas adicionales
                        col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
                        with col_stat1:
                            st.metric("👥 Estudiantes Únicos", df_resultados['user_fullname'].nunique())
                        with col_stat2:
                            st.metric("🎓 Cursos Únicos", df_resultados['course_name'].nunique())
                        with col_stat3:
                            st.metric("👨‍🏫 Docentes Únicos", df_resultados['docente'].nunique())
                        with col_stat4:
                            st.metric("📝 Actividades Únicas", df_resultados['assignment_name'].nunique())
                
                else:  # realizar_busqueda
                    if df_resultados.empty:
                        st.warning("❌ **No se encontraron registros** con los filtros especificados")
                        st.info("💡 **Sugerencia:** Prueba con filtros menos restrictivos o verifica que existan datos para esos criterios")
                    else:
                        st.success(f"✅ **Búsqueda completada:** {len(df_resultados):,} registros encontrados")
                        
                        # Guardar en session state
                        st.session_state['df_busqueda_resultados'] = df_resultados
                        
            except Exception as e:
                st.error(f"❌ Error durante la búsqueda: {str(e)}")
    
    # Mostrar resultados detallados si existen
    if 'df_busqueda_resultados' in st.session_state and not st.session_state['df_busqueda_resultados'].empty:
        st.markdown("---")
        st.subheader("📊 Resultados de la Búsqueda")
        
        df_resultados = st.session_state['df_busqueda_resultados']
        
        # Pestañas para diferentes vistas
        tab1, tab2, tab3 = st.tabs(["📋 Vista Tabla", "📈 Estadísticas", "🔗 Enlaces de Aulas"])
        
        with tab1:
            st.markdown("#### 📋 Datos Detallados")
            
            # Seleccionar columnas a mostrar
            columnas_disponibles = [
                'user_fullname', 'course_name', 'docente', 'assignment_name', 
                'grade', 'has_feedback', 'feedback'
            ]
            columnas_mostrar = st.multiselect(
                "Seleccionar columnas a mostrar:",
                columnas_disponibles,
                default=['user_fullname', 'course_name', 'docente', 'assignment_name', 'grade', 'has_feedback'],
                key="columnas_busqueda"
            )
            
            if columnas_mostrar:
                df_mostrar = df_resultados[columnas_mostrar].rename(columns={
                    'user_fullname': 'Estudiante',
                    'course_name': 'Curso',
                    'docente': 'Docente',
                    'assignment_name': 'Actividad',
                    'grade': 'Calificación',
                    'has_feedback': 'Tiene Feedback',
                    'feedback': 'Feedback'
                })
                
                st.dataframe(df_mostrar, use_container_width=True, height=400)
                
                # Botón de descarga
                csv_data = df_mostrar.to_csv(index=False)
                st.download_button(
                    label="📥 Descargar Resultados (CSV)",
                    data=csv_data,
                    file_name=f"busqueda_supabase_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            else:
                st.warning("⚠️ Selecciona al menos una columna para mostrar")
        
        with tab2:
            st.markdown("#### 📈 Análisis Estadístico")
            
            # Estadísticas generales
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📊 Total Registros", len(df_resultados))
            with col2:
                st.metric("👥 Estudiantes", df_resultados['user_fullname'].nunique())
            with col3:
                st.metric("🎓 Cursos", df_resultados['course_name'].nunique())
            with col4:
                st.metric("👨‍🏫 Docentes", df_resultados['docente'].nunique())
            
            # Distribución por feedback
            col_fb1, col_fb2 = st.columns(2)
            with col_fb1:
                st.markdown("**💬 Distribución de Feedback:**")
                feedback_counts = df_resultados['has_feedback'].value_counts()
                for tiene_feedback, count in feedback_counts.items():
                    label = "Con feedback" if tiene_feedback else "Sin feedback"
                    st.write(f"• {label}: {count:,} ({count/len(df_resultados)*100:.1f}%)")
            
            with col_fb2:
                st.markdown("**📊 Top 5 Cursos:**")
                top_cursos = df_resultados['course_name'].value_counts().head(5)
                for curso, count in top_cursos.items():
                    st.write(f"• {curso}: {count:,}")
        
        with tab3:
            st.markdown("#### 🔗 Enlaces a Aulas Virtuales")
            
            if not df_aulas_enlaces.empty and not df_cursos.empty:
                # Combinar con datos de NRC y enlaces
                df_con_nrc = df_resultados.merge(
                    df_cursos[['id_NRC', 'NRC']], 
                    left_on='course_id', 
                    right_on='id_NRC', 
                    how='left'
                )
                
                df_con_enlaces = df_con_nrc.merge(
                    df_aulas_enlaces[['NRC', 'url']], 
                    on='NRC', 
                    how='left'
                )
                
                aulas_con_enlaces = df_con_enlaces.dropna(subset=['url'])
                
                if not aulas_con_enlaces.empty:
                    st.success(f"🔗 {len(aulas_con_enlaces)} registros tienen enlaces a aulas virtuales")
                    
                    # Mostrar enlaces únicos por NRC
                    enlaces_unicos = aulas_con_enlaces[['course_name', 'NRC', 'url']].drop_duplicates()
                    
                    for _, row in enlaces_unicos.iterrows():
                        st.markdown(f"**🏫 {row['course_name']} (NRC: {row['NRC']})**")
                        st.markdown(f"[🔗 Ir al Aula Virtual]({row['url']})")
                        st.markdown("---")
                else:
                    st.info("ℹ️ No se encontraron enlaces para las aulas de estos resultados")
            else:
                st.warning("⚠️ No se pueden mostrar enlaces (archivos de referencia no disponibles)")

# ==========================
# FUNCIONES PARA FECHAS DE ACTIVIDADES
# ==========================
def obtener_assignments_curso(course_id: int) -> list:
    """Obtiene todas las assignments de un curso (basado en script verificado)"""
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "mod_assign_get_assignments",
        "moodlewsrestformat": "json",
        "courseids[0]": course_id,
        "includenotenrolledcourses": 1  # parámetro requerido para ver cursos sin enrolarse
    }
    
    try:
        resultado = llamar_ws(params)
        assignments = []
        
        for course in resultado.get("courses", []):
            # algunos WS devuelven 'courseid', otros 'id'
            cid = course.get("courseid", course.get("id"))
            if cid != course_id:
                continue
                
            for assignment in course.get("assignments", []):
                # Convertir timestamps a ISO format
                assignment_data = {
                    "assignment_id": assignment.get("id"),
                    "assignment_name": assignment.get("name", ""),
                    "course_id": course_id,
                    "intro": assignment.get("intro", ""),
                    "allowsubmissionsfromdate": assignment.get("allowsubmissionsfromdate"),
                    "duedate": assignment.get("duedate"),
                    "cutoffdate": assignment.get("cutoffdate"),
                    "gradingduedate": assignment.get("gradingduedate"),
                    "allowsubmissionsfromdate_iso": datetime.fromtimestamp(assignment.get("allowsubmissionsfromdate", 0)).isoformat() if assignment.get("allowsubmissionsfromdate") else None,
                    "duedate_iso": datetime.fromtimestamp(assignment.get("duedate", 0)).isoformat() if assignment.get("duedate") else None,
                    "cutoffdate_iso": datetime.fromtimestamp(assignment.get("cutoffdate", 0)).isoformat() if assignment.get("cutoffdate") else None,
                    "gradingduedate_iso": datetime.fromtimestamp(assignment.get("gradingduedate", 0)).isoformat() if assignment.get("gradingduedate") else None,
                }
                assignments.append(assignment_data)
                
        return assignments
        
    except Exception as e:
        print(f"Error obteniendo assignments del curso {course_id}: {e}")
        return []

def obtener_fechas_actividad(course_id: int, assignment_id: int) -> dict:
    """Obtiene fechas de una actividad específica"""
    assignments = obtener_assignments_curso(course_id)
    
    for assignment in assignments:
        if assignment.get("assignment_id") == assignment_id:
            return assignment
    
    return {}

def obtener_estado_entrega(assign_id: int, user_id: int, group_id: int = 0) -> dict:
    """Obtiene el estado de entrega de una tarea específica para un usuario"""
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "mod_assign_get_submission_status",
        "moodlewsrestformat": "json",
        "assignid": assign_id,
        "userid": user_id,
        "groupid": group_id,
    }
    return llamar_ws(params)

def extraer_fechas_entregas_masivo(actividades_df, progreso_callback=None):
    """Extrae fechas de entrega y calificación para múltiples actividades"""
    registros = []
    total_actividades = len(actividades_df)
    
    for i, (_, actividad) in enumerate(actividades_df.iterrows()):
        if progreso_callback:
            progreso_callback((i + 1) / total_actividades)
        
        try:
            assignment_id = actividad['id']
            course_id = actividad['id_curso']
            
            # Obtener participantes
            participantes = obtener_ids_participantes(assignment_id)
            
            for participante in participantes:
                user_id = participante["id"]
                user_fullname = participante["fullname"]
                
                try:
                    # Obtener estado de entrega
                    data = obtener_estado_entrega(assignment_id, user_id)
                    
                    # Extraer fechas de envío y calificación
                    sub_ts = (data.get("lastattempt", {})
                                 .get("submission", {})
                                 .get("timemodified"))
                    
                    grade_ts = (data.get("lastattempt", {}).get("gradeddate")
                               or data.get("feedback", {})
                                      .get("grade", {})
                                      .get("timemodified"))
                    
                    # Obtener información adicional
                    submission_status = data.get("lastattempt", {}).get("submission", {}).get("status", "")
                    submission_plugins = data.get("lastattempt", {}).get("submission", {}).get("plugins", [])
                    
                    registros.append({
                        "assignment_id": assignment_id,
                        "assignment_name": actividad.get('name', ''),
                        "course_id": course_id,
                        "course_name": actividad.get('NomCurso', ''),
                        "docente": actividad.get('DOCENTE', ''),
                        "user_id": user_id,
                        "user_fullname": user_fullname,
                        "submission_date_iso": datetime.fromtimestamp(sub_ts).isoformat() if sub_ts else None,
                        "grading_date_iso": datetime.fromtimestamp(grade_ts).isoformat() if grade_ts else None,
                        "submission_timestamp": sub_ts,
                        "grading_timestamp": grade_ts,
                        "submission_status": submission_status,
                        "has_submission": bool(sub_ts),
                        "has_grading": bool(grade_ts),
                    })
                    
                except Exception as e:
                    print(f"Error procesando usuario {user_id} en actividad {assignment_id}: {e}")
                    continue
                    
        except Exception as e:
            print(f"Error procesando actividad {assignment_id}: {e}")
            continue
    
    return pd.DataFrame(registros)

# ==========================
# PESTAÑA 5: FECHAS DE ACTIVIDADES
# ==========================
def mostrar_pestana_fechas_actividades():
    st.header("📅 Fechas de Actividades y Entregas")
    st.markdown("Extrae fechas de actividades, envíos de estudiantes y calificaciones de profesores")
    
    # Cargar datos
    if not os.path.exists(ASIGNACIONES_CSV) or not os.path.exists(CURSOS_CSV):
        st.error("❌ No se encontraron los archivos CSV necesarios")
        return
    
    try:
        df_asignaciones = pd.read_csv(ASIGNACIONES_CSV)
        df_cursos = pd.read_csv(CURSOS_CSV)
    except Exception as e:
        st.error(f"Error al cargar los archivos CSV: {str(e)}")
        return
    
    # Combinar datos
    df_combinado = df_asignaciones.merge(
        df_cursos[['id_NRC', 'NomCurso', 'DOCENTE', 'Modalidad', 'NRC']], 
        left_on='id_curso', 
        right_on='id_NRC', 
        how='left'
    )
    
    # Crear pestañas para diferentes tipos de extracción
    tab1, tab2 = st.tabs(["📅 Fechas de Actividades", "📤 Fechas de Entregas y Calificaciones"])
    
    with tab1:
        st.subheader("📅 Extraer Fechas de Actividades")
        st.markdown("Obtiene fechas límite, de apertura y cierre de las actividades")
        
        # Filtros similares a otras pestañas
        col1, col2 = st.columns(2)
        
        with col1:
            modalidades_disponibles = ["Todos"] + sorted(df_combinado['Modalidad'].dropna().unique().tolist())
            modalidad_fechas = st.selectbox(
                "Modalidad:",
                modalidades_disponibles,
                key="fechas_modalidad"
            )
        
        with col2:
            # Filtrar por modalidad
            if modalidad_fechas == "Todos":
                df_filtrado_modal = df_combinado.copy()
            else:
                df_filtrado_modal = df_combinado[df_combinado['Modalidad'] == modalidad_fechas]
            
            cursos_disponibles = ["Todos"] + sorted(df_filtrado_modal['NomCurso'].dropna().unique().tolist())
            curso_fechas = st.selectbox(
                "Curso:",
                cursos_disponibles,
                key="fechas_curso"
            )
        
        # Filtrar actividades
        if curso_fechas == "Todos":
            df_actividades_fechas = df_filtrado_modal.copy()
        else:
            df_actividades_fechas = df_filtrado_modal[df_filtrado_modal['NomCurso'] == curso_fechas]
        
        st.info(f"📋 {len(df_actividades_fechas)} actividades disponibles")
        
        if st.button("📅 Extraer Fechas de Actividades", type="primary", key="extraer_fechas_act"):
            with st.spinner("Extrayendo fechas de actividades..."):
                fechas_actividades = []
                progress_bar = st.progress(0)
                
                # Obtener cursos únicos para evitar repeticiones
                cursos_unicos = df_actividades_fechas[['id_curso', 'NomCurso', 'Modalidad']].drop_duplicates()
                
                total_cursos = len(cursos_unicos)
                curso_procesado = 0
                
                for _, curso_row in cursos_unicos.iterrows():
                    try:
                        course_id = int(curso_row['id_curso'])
                        curso_nombre = curso_row['NomCurso']
                        modalidad_curso = curso_row['Modalidad']
                        
                        # Usar la función verificada para obtener todas las assignments del curso
                        assignments = obtener_assignments_curso(course_id)
                        
                        # Obtener información adicional de las actividades del curso en df_actividades_fechas
                        actividades_curso = df_actividades_fechas[df_actividades_fechas['id_curso'] == course_id]
                        
                        for assignment in assignments:
                            # Buscar información adicional en las actividades si existe
                            actividad_info = actividades_curso[actividades_curso['id'] == assignment.get('assignment_id')]
                            
                            if not actividad_info.empty:
                                actividad_row = actividad_info.iloc[0]
                                docente = actividad_row.get('DOCENTE', '')
                                nrc = actividad_row.get('NRC', '')
                            else:
                                docente = ''
                                nrc = ''
                            
                            fecha_info = {
                                'assignment_id': assignment.get('assignment_id'),
                                'assignment_name': assignment.get('assignment_name', ''),
                                'course_id': course_id,
                                'course_name': curso_nombre,
                                'docente': docente,
                                'modalidad': modalidad_curso,
                                'nrc': nrc,
                                'intro': assignment.get('intro', ''),
                                'allowsubmissionsfromdate': assignment.get('allowsubmissionsfromdate'),
                                'duedate': assignment.get('duedate'),
                                'cutoffdate': assignment.get('cutoffdate'),
                                'gradingduedate': assignment.get('gradingduedate'),
                                'allowsubmissionsfromdate_iso': assignment.get('allowsubmissionsfromdate_iso'),
                                'duedate_iso': assignment.get('duedate_iso'),
                                'cutoffdate_iso': assignment.get('cutoffdate_iso'),
                                'gradingduedate_iso': assignment.get('gradingduedate_iso'),
                            }
                            fechas_actividades.append(fecha_info)
                        
                        curso_procesado += 1
                        progress_bar.progress(curso_procesado / total_cursos)
                        
                    except Exception as e:
                        st.warning(f"Error extrayendo fechas del curso {curso_row['NomCurso']}: {e}")
                        curso_procesado += 1
                        progress_bar.progress(curso_procesado / total_cursos)
                
                if fechas_actividades:
                    df_fechas_act = pd.DataFrame(fechas_actividades)
                    st.session_state['df_fechas_actividades'] = df_fechas_act
                    st.success(f"✅ Fechas extraídas para {len(fechas_actividades)} actividades de {total_cursos} cursos")
                else:
                    st.warning("❌ No se pudieron extraer fechas de actividades")
        
        # Mostrar resultados de fechas de actividades
        if 'df_fechas_actividades' in st.session_state:
            st.markdown("---")
            st.subheader("📊 Fechas de Actividades")
            
            df_fechas = st.session_state['df_fechas_actividades']
            
            # Seleccionar columnas a mostrar
            columnas_fechas = [
                'assignment_name', 'course_name', 'docente', 'modalidad', 'nrc',
                'allowsubmissionsfromdate_iso', 'duedate_iso', 'cutoffdate_iso', 'gradingduedate_iso'
            ]
            
            df_mostrar_fechas = df_fechas[columnas_fechas].rename(columns={
                'assignment_name': 'Actividad',
                'course_name': 'Curso',
                'docente': 'Docente',
                'modalidad': 'Modalidad',
                'nrc': 'NRC',
                'allowsubmissionsfromdate_iso': 'Fecha Apertura',
                'duedate_iso': 'Fecha Límite',
                'cutoffdate_iso': 'Fecha Corte',
                'gradingduedate_iso': 'Fecha Límite Calificación'
            })
            
            st.dataframe(df_mostrar_fechas, use_container_width=True, height=400)
            
            # Descarga
            csv_fechas = df_mostrar_fechas.to_csv(index=False)
            st.download_button(
                label="📥 Descargar Fechas de Actividades (CSV)",
                data=csv_fechas,
                file_name=f"fechas_actividades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    
    with tab2:
        st.subheader("📤 Extraer Fechas de Entregas y Calificaciones")
        st.markdown("Obtiene fechas de envío de estudiantes y calificación de profesores")
        
        # Selector de tipo de extracción
        tipo_extraccion_fechas = st.selectbox(
            "Tipo de extracción:",
            [
                "Actividad específica",
                "Todas las actividades de un curso",
                "Todas las actividades de un profesor"
            ],
            key="tipo_extraccion_fechas"
        )
        
        actividades_seleccionadas_fechas = pd.DataFrame()
        
        if tipo_extraccion_fechas == "Actividad específica":
            # Filtros para actividad específica
            col1, col2, col3 = st.columns(3)
            
            with col1:
                modalidad_sel = st.selectbox(
                    "Modalidad:",
                    ["Todos"] + sorted(df_combinado['Modalidad'].dropna().unique().tolist()),
                    key="fechas_ent_modalidad"
                )
            
            with col2:
                if modalidad_sel == "Todos":
                    df_filt_mod = df_combinado.copy()
                else:
                    df_filt_mod = df_combinado[df_combinado['Modalidad'] == modalidad_sel]
                
                curso_sel = st.selectbox(
                    "Curso:",
                    ["Todos"] + sorted(df_filt_mod['NomCurso'].dropna().unique().tolist()),
                    key="fechas_ent_curso"
                )
            
            with col3:
                if curso_sel == "Todos":
                    df_filt_curso = df_filt_mod.copy()
                else:
                    df_filt_curso = df_filt_mod[df_filt_mod['NomCurso'] == curso_sel]
                
                docente_sel = st.selectbox(
                    "Docente:",
                    ["Todos"] + sorted(df_filt_curso['DOCENTE'].dropna().unique().tolist()),
                    key="fechas_ent_docente"
                )
            
            # Filtrar actividades
            if docente_sel == "Todos":
                df_final = df_filt_curso.copy()
            else:
                df_final = df_filt_curso[df_filt_curso['DOCENTE'] == docente_sel]
            
            if not df_final.empty:
                actividades_info = []
                for _, row in df_final.iterrows():
                    info = f"{row['NomCurso']} - {row['name']} (Docente: {row['DOCENTE']})"
                    actividades_info.append((info, row))
                
                if actividades_info:
                    actividad_sel_idx = st.selectbox(
                        "Seleccionar Actividad:",
                        range(len(actividades_info)),
                        format_func=lambda x: actividades_info[x][0],
                        key="actividad_fechas_especifica"
                    )
                    
                    if actividad_sel_idx is not None:
                        row_seleccionada = actividades_info[actividad_sel_idx][1]
                        actividades_seleccionadas_fechas = pd.DataFrame([row_seleccionada])
        
        elif tipo_extraccion_fechas == "Todas las actividades de un curso":
            curso_sel_masivo = st.selectbox(
                "Seleccionar Curso:",
                sorted(df_combinado['NomCurso'].dropna().unique()),
                key="curso_fechas_masivo"
            )
            actividades_seleccionadas_fechas = df_combinado[df_combinado['NomCurso'] == curso_sel_masivo]
        
        elif tipo_extraccion_fechas == "Todas las actividades de un profesor":
            docente_sel_masivo = st.selectbox(
                "Seleccionar Profesor:",
                sorted(df_combinado['DOCENTE'].dropna().unique()),
                key="docente_fechas_masivo"
            )
            actividades_seleccionadas_fechas = df_combinado[df_combinado['DOCENTE'] == docente_sel_masivo]
        
        if not actividades_seleccionadas_fechas.empty:
            st.info(f"📋 Se procesarán {len(actividades_seleccionadas_fechas)} actividades")
            
            if st.button("📤 Extraer Fechas de Entregas", type="primary", key="extraer_fechas_ent"):
                with st.spinner("Extrayendo fechas de entregas y calificaciones... Esto puede tomar varios minutos."):
                    progress_bar = st.progress(0)
                    
                    def actualizar_progreso(progreso):
                        progress_bar.progress(progreso)
                    
                    df_entregas = extraer_fechas_entregas_masivo(
                        actividades_seleccionadas_fechas, 
                        progreso_callback=actualizar_progreso
                    )
                    
                    if not df_entregas.empty:
                        st.session_state['df_fechas_entregas'] = df_entregas
                        st.success(f"✅ Fechas de entregas extraídas: {len(df_entregas)} registros")
                    else:
                        st.warning("❌ No se pudieron extraer fechas de entregas")
        
        # Mostrar resultados de fechas de entregas
        if 'df_fechas_entregas' in st.session_state:
            st.markdown("---")
            st.subheader("📊 Fechas de Entregas y Calificaciones")
            
            df_entregas = st.session_state['df_fechas_entregas']
            
            # Estadísticas
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📊 Total Registros", len(df_entregas))
            with col2:
                st.metric("📤 Con Entrega", len(df_entregas[df_entregas['has_submission']]))
            with col3:
                st.metric("📝 Calificados", len(df_entregas[df_entregas['has_grading']]))
            with col4:
                st.metric("👥 Estudiantes", df_entregas['user_fullname'].nunique())
            
            # Filtros para mostrar resultados
            st.subheader("🔧 Filtros de Resultados")
            col_filt1, col_filt2 = st.columns(2)
            
            with col_filt1:
                filtro_entrega = st.selectbox(
                    "Estado de Entrega:",
                    ["Todos", "Con entrega", "Sin entrega"],
                    key="filtro_entrega_fechas"
                )
            
            with col_filt2:
                filtro_calificacion = st.selectbox(
                    "Estado de Calificación:",
                    ["Todos", "Calificados", "Sin calificar"],
                    key="filtro_calificacion_fechas"
                )
            
            # Aplicar filtros
            df_mostrar_entregas = df_entregas.copy()
            
            if filtro_entrega == "Con entrega":
                df_mostrar_entregas = df_mostrar_entregas[df_mostrar_entregas['has_submission']]
            elif filtro_entrega == "Sin entrega":
                df_mostrar_entregas = df_mostrar_entregas[~df_mostrar_entregas['has_submission']]
            
            if filtro_calificacion == "Calificados":
                df_mostrar_entregas = df_mostrar_entregas[df_mostrar_entregas['has_grading']]
            elif filtro_calificacion == "Sin calificar":
                df_mostrar_entregas = df_mostrar_entregas[~df_mostrar_entregas['has_grading']]
            
            # Tabla de resultados
            columnas_entregas = [
                'user_fullname', 'assignment_name', 'course_name', 'docente',
                'submission_date_iso', 'grading_date_iso', 'submission_status'
            ]
            
            df_tabla_entregas = df_mostrar_entregas[columnas_entregas].rename(columns={
                'user_fullname': 'Estudiante',
                'assignment_name': 'Actividad',
                'course_name': 'Curso',
                'docente': 'Docente',
                'submission_date_iso': 'Fecha Entrega',
                'grading_date_iso': 'Fecha Calificación',
                'submission_status': 'Estado Entrega'
            })
            
            st.dataframe(df_tabla_entregas, use_container_width=True, height=400)
            
            # Descargas
            col_desc1, col_desc2 = st.columns(2)
            
            with col_desc1:
                csv_entregas = df_tabla_entregas.to_csv(index=False)
                st.download_button(
                    label="📥 Descargar Entregas (CSV)",
                    data=csv_entregas,
                    file_name=f"fechas_entregas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            
            with col_desc2:
                json_entregas = df_mostrar_entregas.to_json(orient='records', date_format='iso', indent=2)
                st.download_button(
                    label="📥 Descargar Entregas (JSON)",
                    data=json_entregas,
                    file_name=f"fechas_entregas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )

# ==========================
# INTERFAZ PRINCIPAL CON PESTAÑAS
# ==========================
def main():
    st.set_page_config(
        page_title="Extractor de Calificaciones Moodle",
        page_icon="📊",
        layout="wide"
    )
    
    st.title("Extractor de Calificaciones y Feedback - ISIL+")
    
    # Verificar conexión a Supabase
    if verificar_conexion_supabase():
        st.sidebar.success("🗄️ Conectado a Supabase")
    else:
        st.sidebar.error("❌ Error de conexión a Supabase")
        st.sidebar.warning("La aplicación usará solo cache local")
    
    st.markdown("---")
    
    # Crear pestañas
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Extracción Individual", "📊 Extracción Masiva", "🔍 Análisis de Casos", "🔍 Búsqueda en Supabase", "📅 Fechas de Actividades"])
    
    with tab1:
        mostrar_pestana_individual()
    
    with tab2:
        mostrar_pestana_masiva()
    
    with tab3:
        mostrar_pestana_casos_especiales()
    
    with tab4:
        mostrar_pestana_busqueda_supabase()
    
    with tab5:
        mostrar_pestana_fechas_actividades()
    
    # Gestión de cache en la sidebar
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Gestión de Cache")
    
    # Información sobre el sistema de cache
    with st.sidebar.expander("ℹ️ ¿Cómo funciona el Cache?"):
        st.markdown("""
        **🔄 Sistema de 3 Niveles:**
        
        1. **🗄️ Supabase** (Principal)
           - Base de datos en la nube
           - Datos compartidos globalmente
           
        2. **📋 Cache Local Individual**
           - Consultas específicas (curso + actividad)
           - Almacenado en CSV local
           
        3. **📊 Cache Local Masivo**
           - Consultas masivas (múltiples actividades)
           - Optimizado para extracciones grandes
           
        **⚡ Beneficios:**
        - Reduce tiempo de carga de 30s a 2s
        - Evita consultas repetitivas a Moodle
        - Funciona offline después de la primera carga
        """)
    
    # Cache individual
    cache_individual_existe = os.path.exists(CACHE_CSV)
    if cache_individual_existe:
        try:
            cache_df = pd.read_csv(CACHE_CSV)
            if not cache_df.empty:
                consultas_individuales = len(cache_df.groupby('cache_key'))
                registros_individuales = len(cache_df)
                st.sidebar.success(f"📋 Cache Individual: {consultas_individuales} consultas ({registros_individuales:,} registros)")
                
                # Mostrar última actualización si existe timestamp
                if 'timestamp' in cache_df.columns:
                    ultima_actualizacion = pd.to_datetime(cache_df['timestamp']).max()
                    st.sidebar.caption(f"Última actualización: {ultima_actualizacion.strftime('%d/%m/%Y %H:%M')}")
            else:
                st.sidebar.info("📋 Cache Individual: Vacío")
        except Exception as e:
            st.sidebar.error(f"Error al leer cache individual: {str(e)}")
    else:
        st.sidebar.info("📋 Cache Individual: No inicializado")
    
    # Cache masivo
    cache_masivo_existe = os.path.exists(CACHE_MASIVO_CSV)
    if cache_masivo_existe:
        try:
            cache_masivo_df = pd.read_csv(CACHE_MASIVO_CSV)
            if not cache_masivo_df.empty:
                consultas_masivas = len(cache_masivo_df.groupby('cache_key'))
                registros_masivos = len(cache_masivo_df)
                st.sidebar.success(f"📊 Cache Masivo: {consultas_masivas} consultas ({registros_masivos:,} registros)")
                
                # Mostrar última actualización si existe timestamp
                if 'timestamp' in cache_masivo_df.columns:
                    ultima_actualizacion = pd.to_datetime(cache_masivo_df['timestamp']).max()
                    st.sidebar.caption(f"Última actualización: {ultima_actualizacion.strftime('%d/%m/%Y %H:%M')}")
            else:
                st.sidebar.info("📊 Cache Masivo: Vacío")
        except Exception as e:
            st.sidebar.error(f"Error al leer cache masivo: {str(e)}")
    else:
        st.sidebar.info("📊 Cache Masivo: No inicializado")
    
    # Botones de limpieza
    col1, col2 = st.sidebar.columns(2)
    
    with col1:
        if cache_individual_existe and st.button("🗑️ Limpiar Individual", help="Elimina el cache de consultas individuales"):
            try:
                os.remove(CACHE_CSV)
                st.sidebar.success("Cache individual limpiado")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Error: {str(e)}")
    
    with col2:
        if cache_masivo_existe and st.button("🗑️ Limpiar Masivo", help="Elimina el cache de consultas masivas"):
            try:
                os.remove(CACHE_MASIVO_CSV)
                st.sidebar.success("Cache masivo limpiado")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Error: {str(e)}")
    
    # Botón para limpiar todo
    if cache_individual_existe or cache_masivo_existe:
        if st.sidebar.button("🧹 Limpiar Todo el Cache", type="secondary"):
            try:
                files_removed = 0
                if cache_individual_existe:
                    os.remove(CACHE_CSV)
                    files_removed += 1
                if cache_masivo_existe:
                    os.remove(CACHE_MASIVO_CSV)
                    files_removed += 1
                st.sidebar.success(f"✅ {files_removed} archivo(s) de cache eliminados")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Error al limpiar cache: {str(e)}")

if __name__ == "__main__":
    main() 