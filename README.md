# 📊 Extractor de Calificaciones Moodle

Una aplicación Streamlit para extraer calificaciones y feedback de Moodle con funcionalidades avanzadas de análisis y almacenamiento.

## 🚀 Características

- **Extracción Individual**: Calificaciones y feedback de actividades específicas
- **Extracción Masiva**: Múltiples actividades en formato matriz
- **Análisis de Casos Especiales**: Identificación de estudiantes que requieren atención
- **Cache Inteligente**: Sistema de cache local y en Supabase para optimizar rendimiento
- **Filtros Avanzados**: Por curso, docente, modalidad y criterios específicos
- **Exportación**: Descarga de resultados en formato CSV

## 📋 Requisitos

- Python 3.8 o superior
- Cuenta de Moodle con token de API
- Cuenta de Supabase (opcional, para cache compartido)

## 🛠️ Instalación

### 1. Clonar el repositorio
```bash
git clone https://github.com/tu-usuario/extractor-calificaciones-moodle.git
cd extractor-calificaciones-moodle
```

### 2. Crear entorno virtual
```bash
python -m venv venv
# En Windows:
venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
```bash
# Copiar el archivo de ejemplo
cp .env.example .env.local

# Editar .env.local con tus valores reales
```

### 5. Preparar archivos CSV
Coloca los siguientes archivos en el directorio raíz:
- `asignaciones_evaluaciones.csv`: Datos de actividades y evaluaciones
- `cursos.csv`: Información de cursos y docentes

## ⚙️ Configuración

### Variables de entorno (.env.local)

```env
# Configuración de Moodle (OBLIGATORIO)
MOODLE_URL=https://tu-moodle-url.com
MOODLE_TOKEN=tu_token_de_moodle_aqui

# Configuración de Supabase (OPCIONAL)
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu_supabase_anon_key_aqui

# Configuración de cache
CACHE_ENABLED=true
CACHE_EXPIRY_HOURS=24
```

### Obtener Token de Moodle

1. Inicia sesión en tu Moodle
2. Ve a **Preferencias del usuario** → **Tokens de seguridad**
3. Crea un nuevo token con los permisos necesarios
4. Copia el token a tu archivo `.env.local`

### Configurar Supabase (Opcional)

Si quieres usar cache compartido:

1. Crea una cuenta en [Supabase](https://supabase.com)
2. Crea un nuevo proyecto
3. Ejecuta este SQL en el editor de Supabase:

```sql
-- Crear tabla para cache de calificaciones
CREATE TABLE calificaciones_feedback (
    id SERIAL PRIMARY KEY,
    course_id INTEGER NOT NULL,
    assignment_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    user_fullname TEXT NOT NULL,
    assignment_name TEXT NOT NULL,
    course_name TEXT NOT NULL,
    docente TEXT NOT NULL,
    grade TEXT,
    has_feedback BOOLEAN NOT NULL DEFAULT false,
    feedback TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Crear índices para optimizar consultas
CREATE INDEX idx_calificaciones_course_assignment ON calificaciones_feedback(course_id, assignment_id);
CREATE INDEX idx_calificaciones_user ON calificaciones_feedback(user_id);
CREATE INDEX idx_calificaciones_course_name ON calificaciones_feedback(course_name);
CREATE INDEX idx_calificaciones_docente ON calificaciones_feedback(docente);

-- Crear constraint único para evitar duplicados
ALTER TABLE calificaciones_feedback 
ADD CONSTRAINT unique_calificacion 
UNIQUE (course_id, assignment_id, user_id);

-- Habilitar Row Level Security
ALTER TABLE calificaciones_feedback ENABLE ROW LEVEL SECURITY;

-- Crear política para permitir todas las operaciones (ajustar según necesidades)
CREATE POLICY "Enable all operations for authenticated users" ON calificaciones_feedback
    FOR ALL USING (true);
```

4. Copia la URL y la clave anónima a tu `.env.local`

## 🚀 Uso

### Ejecutar la aplicación
```bash
streamlit run app_calificaciones.py
```

### Estructura de archivos CSV

#### asignaciones_evaluaciones.csv
```csv
id_curso,cmid,id,name
12345,67890,111,Evaluación Integral
12345,67891,112,Proceso de Aprendizaje 1
```

#### cursos.csv
```csv
NRC,id_NRC,CodCurso,fullname_isil,NomCurso,Modalidad,Tipo,EsquemaEval,DOCENTE
12345,12345,ABC123,Nombre Completo,CURSO EJEMPLO,PRE,REGULAR,Normal,APELLIDO, NOMBRE
```

## 📊 Funcionalidades

### 1. Extracción Individual
- Selecciona una actividad específica
- Extrae calificaciones y feedback detallado
- Filtros avanzados de resultados

### 2. Extracción Masiva
- Todas las actividades de un curso
- Todas las actividades de un profesor
- Todas las actividades de un aula específica
- Formato matriz (estudiantes vs actividades)

### 3. Análisis de Casos Especiales
- **Calificación 16-18 sin feedback**: Estudiantes destacados sin retroalimentación
- **Calificación 14-15 sin feedback**: Estudiantes regulares que necesitan feedback
- **Calificación 1-13 sin feedback**: Estudiantes con dificultades sin retroalimentación
- **Sin calificación en actividades específicas**: Estudiantes sin evaluar

## 🔧 Optimización

### Sistema de Cache
La aplicación utiliza un sistema de cache de tres niveles:

1. **Supabase** (compartido, persistente)
2. **Cache Local CSV** (rápido, local)
3. **Moodle API** (último recurso)

Esto reduce significativamente las consultas a Moodle (hasta 90% menos).

### Rendimiento
- Consultas en lote para optimizar velocidad
- Barras de progreso para operaciones largas
- Manejo inteligente de errores
- Degradación elegante si Supabase no está disponible

## 🐛 Solución de Problemas

### Error de conexión a Moodle
- Verifica que el token sea válido
- Confirma que la URL de Moodle sea correcta
- Asegúrate de que el token tenga los permisos necesarios

### Error de conexión a Supabase
- La aplicación funcionará solo con cache local
- Verifica las credenciales en `.env.local`
- Confirma que la tabla esté creada correctamente

### Archivos CSV no encontrados
- Asegúrate de que `asignaciones_evaluaciones.csv` y `cursos.csv` estén en el directorio raíz
- Verifica que los archivos tengan las columnas correctas

## 🤝 Contribución

1. Fork del proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📝 Licencia

Este proyecto está bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para detalles.

## 👥 Autor

**Tu Nombre** - [@tu-usuario](https://github.com/tu-usuario)

## 🙏 Agradecimientos

- Streamlit por el framework de aplicaciones web
- Supabase por la base de datos en la nube
- Moodle por la API de integración 