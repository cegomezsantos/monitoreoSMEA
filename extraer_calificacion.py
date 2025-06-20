# ==========================
# EXTRAE CALIFICACIONES Y FEEDBACK DE LOS ALUMNOS DE UNA ACTIVIDAD
# ==========================



import requests
import csv
import time

# ==========================
# CONFIGURACIÓN INICIAL
# ==========================
MOODLE_BASE_URL = "https://platform.ecala.net/webservice/rest/server.php"
MOODLE_TOKEN    = "7a5d0b50bfca46455a93ef404a608f81"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded"
}

COURSE_ID       = 32561    # ← Reemplaza con el ID de tu curso
ASSIGNMENT_ID   = 181726   # ← Reemplaza con el ID de la assignment que verificaste
GROUP_ID        = 0        # 0 = todos los grupos
FILTER_STR      = ""       # cadena vacía = sin filtro
INCLUDE_ENROL   = 1        # 1 = solo usuarios matriculados

# Guardar el CSV en el directorio actual
CSV_PATH = "feedback.csv"


def llamar_ws(params: dict) -> dict:
    """
    Envía la petición POST al endpoint REST de Moodle y devuelve el JSON decodificado.
    Lanza excepción si hay un error HTTP.
    """
    resp = requests.post(MOODLE_BASE_URL, data=params, headers=HEADERS, verify=True)
    resp.raise_for_status()
    return resp.json()


def obtener_nombre_assignment(course_id: int, assignment_id: int) -> str:
    """
    Llama a mod_assign_get_assignments para obtener el nombre de la assignment.
    """
    params = {
        "wstoken":            MOODLE_TOKEN,
        "wsfunction":         "mod_assign_get_assignments",
        "moodlewsrestformat": "json",
        "courseids[0]":       course_id
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
    """
    Llama a mod_assign_get_grades para la assignment indicada.
    Retorna dict {userid: grade}.
    """
    params = {
        "wstoken":            MOODLE_TOKEN,
        "wsfunction":         "mod_assign_get_grades",
        "moodlewsrestformat": "json",
        "assignmentids[0]":   assignment_id
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
    """
    Llama a mod_assign_list_participants y retorna lista de dicts {'id', 'fullname'}.
    """
    params = {
        "wstoken":            MOODLE_TOKEN,
        "wsfunction":         "mod_assign_list_participants",
        "moodlewsrestformat": "json",
        "assignid":           assignment_id,
        "groupid":            GROUP_ID,
        "filter":             FILTER_STR,
        "includeenrolments":  INCLUDE_ENROL
    }
    resultado = llamar_ws(params)

    # Si devuelve excepción, avisamos y retornamos vacío
    if isinstance(resultado, dict) and resultado.get("exception"):
        print("ERROR en mod_assign_list_participants:")
        print(f"  exception: {resultado.get('exception')}")
        print(f"  errorcode: {resultado.get('errorcode')}")
        print(f"  message: {resultado.get('message')}\n")
        return []

    # Determinar la lista de usuarios según el formato de resultado
    if isinstance(resultado, list):
        usuarios = resultado
    elif isinstance(resultado, dict):
        usuarios = resultado.get("users", [])
    else:
        usuarios = []

    participantes = []
    for u in usuarios:
        uid = u.get("id")
        fullname = u.get("fullname", "")
        participantes.append({"id": uid, "fullname": fullname})
    return participantes


def obtener_feedback(assignment_id: int, user_id: int) -> str:
    """
    Llama a mod_assign_get_submission_status y extrae texto completo de feedback del plugin "comments".
    """
    params = {
        "wstoken":            MOODLE_TOKEN,
        "wsfunction":         "mod_assign_get_submission_status",
        "moodlewsrestformat": "json",
        "assignid":           assignment_id,
        "userid":             user_id,
        "groupid":            GROUP_ID
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
# CREAR CSV
# ==========================
def procesar_feedback_completo(assignment_id: int, course_id: int):
    assignment_name = obtener_nombre_assignment(course_id, assignment_id)
    grades_dict     = obtener_grades(assignment_id)
    participantes    = obtener_ids_participantes(assignment_id)

    with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "assignment_id",
            "assignment_name",
            "user_id",
            "user_fullname",
            "grade",
            "feedback"
        ])

        inicio = time.time()
        for p in participantes:
            uid = p["id"]
            fullname = p["fullname"]
            grade = grades_dict.get(uid, "")
            feedback = obtener_feedback(assignment_id, uid)
            writer.writerow([
                assignment_id,
                assignment_name,
                uid,
                fullname,
                grade,
                feedback
            ])
        total_time = time.time() - inicio

    print(f"CSV generado exitosamente: {CSV_PATH}")
    print(f"Tiempo total de creación: {total_time:.2f} segundos.")


if __name__ == "__main__":
    procesar_feedback_completo(ASSIGNMENT_ID, COURSE_ID)

