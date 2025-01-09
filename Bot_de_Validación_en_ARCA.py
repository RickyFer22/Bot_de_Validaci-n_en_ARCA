import requests
import json
import logging
import datetime
import time
import pandas as pd
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from threading import Thread, Event
import queue
import sys
import os
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter, Retry
import matplotlib.pyplot as plt
import analisis_avanzado  # Importa el módulo para el análisis avanzado
import re

# Obtener la ruta del directorio actual donde se ejecuta el script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Configuración del log
log_filename = os.path.join(script_dir, 'Validación_en_ARCA.log')
logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

# Configuración de la API
TANGO_API_URL = "http://server:17000/Api/Get"  # Reemplaza con la URL de tu API
AFIP_API_URL = "https://api-constancias-de-inscripcion.mrbot.com.ar/consulta_constancia/"

# Función para leer las claves desde el archivo claves.txt
def leer_claves(filepath):
    claves = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)  # Separa solo en la primera ocurrencia de '='
                    claves[key] = value
                else:
                    logging.warning(f"Línea inválida en el archivo de claves: {line.strip()}")
    except FileNotFoundError:
        logging.error(f"Archivo de claves no encontrado: {filepath}")
        print(f"Error: Archivo de claves no encontrado en: {filepath}")
    except Exception as e:
        logging.error(f"Error al leer el archivo de claves: {e}")
        print(f"Error al leer el archivo de claves: {e}")
    return claves

# Leer las claves desde el archivo
claves = leer_claves(os.path.join(script_dir, 'Access_Key.txt'))

# Asignar las claves a las variables correspondientes
TANGO_API_TOKEN = claves.get('TANGO_API_TOKEN')
TANGO_COMPANY_ID = claves.get('TANGO_COMPANY_ID')
AFIP_USER = claves.get('AFIP_USER')
AFIP_API_KEY = claves.get('AFIP_API_KEY')

# Verificar que las claves no estén vacías
if not all([TANGO_API_TOKEN, TANGO_COMPANY_ID, AFIP_USER, AFIP_API_KEY]):
    logging.error("Error: Falta alguna clave en el archivo de claves.")
    print("Error: Falta alguna clave en el archivo de claves.")
    sys.exit()

# Configuración de la sesión de requests con reintentos
def configurar_sesion():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

session = configurar_sesion()

# Función para obtener datos de la API de Tango Gestión
def obtener_datos_tango(process, page_size=10000, page_index=0):
    headers = {
        "ApiAuthorization": TANGO_API_TOKEN,
        "Company": TANGO_COMPANY_ID
    }
    params = {
        "process": process,
        "pageSize": page_size,
        "pageIndex": page_index,
        "view": ""
    }
    try:
        response = session.get(TANGO_API_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return data["resultData"]["list"]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error en la solicitud a la API de Tango: {e}")
        print(f"Error en la solicitud a la API de Tango: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Error al decodificar la respuesta JSON de Tango: {e}")
        print(f"Error al decodificar la respuesta JSON de Tango: {e}")
        return []

# Función para obtener el número total de páginas de la API de Tango
def obtener_paginacion_tango(process):
    headers = {
        "ApiAuthorization": TANGO_API_TOKEN,
        "Company": TANGO_COMPANY_ID
    }
    params = {
        "process": process,
        "pageSize": 5000,
        "pageIndex": 0,
        "view": ""
    }
    try:
        response = session.get(TANGO_API_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return data["resultData"]["totalPages"]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al obtener la paginación de la API de Tango: {e}")
        print(f"Error al obtener la paginación de la API de Tango: {e}")
        return 0
    except json.JSONDecodeError as e:
        logging.error(f"Error al decodificar la respuesta JSON de Tango al obtener paginación: {e}")
        print(f"Error al decodificar la respuesta JSON de Tango al obtener paginación: {e}")
        return 0

# Función para validar CUIT con la API de AFIP
def validar_cuit_afip(cuit):
    params = {
        "cuit": cuit,
        "usuario": AFIP_USER,
        "api_key": AFIP_API_KEY
    }
    try:
        response = session.get(AFIP_API_URL, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al consultar la API de AFIP para el CUIT {cuit}: {e}")
        print(f"Error al consultar la API de AFIP para el CUIT {cuit}: {e}")
        return {"error": str(e)}
    except json.JSONDecodeError as e:
        logging.error(f"Error al decodificar la respuesta JSON de AFIP para el CUIT {cuit}: {e}")
        print(f"Error al decodificar la respuesta JSON de AFIP para el CUIT {cuit}: {e}")
        return {"error": "Error al decodificar la respuesta JSON"}

# Función para validar CUITs en paralelo
def validar_cuits_en_paralelo(clientes):
    resultados = []
    with ThreadPoolExecutor(max_workers=5) as executor:  # 5 hilos simultáneos
        futures = [executor.submit(validar_cuit_afip, cliente["CUIT"]) for cliente in clientes]
        for future, cliente in zip(futures, clientes):
            resultado = future.result()
            resultados.append({"cliente": cliente, "validacion": resultado})
    return resultados

# Función para filtrar clientes según condiciones
def filtrar_clientes(clientes):
    return [
        cliente for cliente in clientes
        if cliente.get("CUIT", "")
        and cliente.get("COD_GVA14", "")[-1:].upper() == "F"
        and cliente.get("HABILITADO") is True
    ]

# Función para validar el formato del CUIT
def es_cuit_valido(cuit):
    cuit_regex = re.compile(r'^\d{2}-?\d{7,8}-?\d{1}$')
    return bool(cuit_regex.match(cuit))


# Función para guardar resultados parciales en CSV
def guardar_parcialmente(resultados, filename="parcial_resultados.csv"):
    if not resultados:  # Verifica que haya resultados para guardar
        return
    df = pd.DataFrame(resultados)
    df.to_csv(filename, index=False, mode='a', header=not os.path.exists(filename))

# Función para generar reporte visual
def generar_reporte_visual(resultados):
    activos = sum(1 for r in resultados if r["Detalles de la Baja"] == "Sin errores")
    inactivos = len(resultados) - activos

    plt.bar(["Activos", "Inactivos"], [activos, inactivos], color=["green", "red"])
    plt.title("Resultado de la Validación de CUITs")
    plt.xlabel("Estado")
    plt.ylabel("Cantidad")
    plt.savefig("reporte.png")
    plt.show(block=False)  # Evita bloquear la interfaz gráfica

class ConsoleOutput(tk.Text):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.queue = queue.Queue()
        self.update_me()
        
    def write(self, text):
        self.queue.put(text)
        
    def flush(self):
        pass
        
    def update_me(self):
        while not self.queue.empty():
            text = self.queue.get()
            self.configure(state='normal')
            self.insert('end', text)
            self.see('end')
            self.configure(state='disabled')
        self.after(100, self.update_me)

class ModernApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bot Tango Gestión-Arca")
        self.root.geometry("900x700")
        
        # Colores personalizados
        bg_color = "#2b2b2b"  # Gris oscuro
        text_color = "#0f0d0d"  # Negro
        button_color = "#4CAF50"  # Verde
        progress_color = "#4CAF50" # Verde

        self.root.configure(bg=bg_color)
        self.root.iconbitmap(os.path.join(script_dir, "icono.ico"))

        # Configurar estilos
        self.configure_styles(bg_color, text_color, button_color, progress_color)

        # Frame principal
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Título personalizado
        title_label = ttk.Label(
            self.main_frame,
            text="🤖 Bot de Validación en ARCA: Detecta Clientes con CUIT Inactivo",  # Emoji y texto más conciso
            font=('Montserrat', 24, 'bold'),  # Fuente más moderna y tamaño más grande
            foreground='#2C3E50',  # Azul oscuro elegante
            background='#ECF0F1'  # Fondo gris muy claro
        )
        title_label.pack(pady=20)

        # Subtítulo
        subtitle_label = ttk.Label(
            self.main_frame,
            text="Integración API Tango Gestión & Mr. Bot",
            font=('Montserrat', 14, 'italic'),  # Subtítulo en cursiva
            foreground='#7F8C8D',  # Gris medio para el subtítulo
            background='#ECF0F1'  # Mismo fondo que el título
        )
        subtitle_label.pack(pady=(0,15))  # Menos espacio arriba, más abajo

    
        # Frame para controles
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, pady=10)
        # Frame para todos los botones (horizontal)
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(pady=10, fill=tk.X)
        # Entry y botones en la misma fila
        self.output_path = tk.StringVar()
        self.output_path.set("Seleccione directorio de salida...")
        path_entry = ttk.Entry(button_frame, textvariable=self.output_path, width=50, state='readonly', style="Custom.TEntry")
        path_entry.pack(side=tk.LEFT, padx=5)
        dir_button = ttk.Button(
            button_frame,
            text="Elegir directorio",
            style="Custom.TButton",
            command=self.select_directory
        )
        dir_button.pack(side=tk.LEFT, padx=5)
        # Botón de inicio
        self.start_button = ttk.Button(
            button_frame,
            text="Iniciar Proceso",
            style="Custom.TButton",
            command=self.iniciar_proceso_thread,
            state=tk.DISABLED
        )
        self.start_button.pack(side=tk.LEFT, padx=5)
        # Botón de detener
        self.stop_event = Event()
        self.stop_button = ttk.Button(
            button_frame,
            text="Detener Proceso",
            style="Custom.TButton",
            command=self.stop_proceso
        )
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.stop_button.config(state=tk.DISABLED)
        # Botón de información
        self.info_button = ttk.Button(
            button_frame,
            text="Info",
            style="Custom.TButton",
            command=self.mostrar_info
        )
        self.info_button.pack(side=tk.LEFT, padx=5)
        # Botón para exportar el log
        self.export_log_button = ttk.Button(
            button_frame,
            text="Exportar Log",
            style="Custom.TButton",
            command=self.exportar_log
        )
        self.export_log_button.pack(side=tk.LEFT, padx=5)
        # Botón de Dashboard
        self.dashboard_button = ttk.Button(
            button_frame,
            text="Dashboard",
            style="Custom.TButton",
            command=self.open_dashboard
        )
        self.dashboard_button.pack(side=tk.LEFT, padx=5)

        # Barra de progreso mejorada
        self.progress = ttk.Progressbar(
            self.main_frame,
            orient="horizontal",
            length=600,
            mode="determinate",
            style="Custom.Horizontal.TProgressbar"
        )
        self.progress.pack(fill=tk.X, pady=10)

        # Estado
        self.status_label = ttk.Label(
            self.main_frame,
            text="Estado: En espera",
            font=('Helvetica', 10),
            foreground=text_color # Texto 
        )
        self.status_label.pack(pady=5)

        # Consola mejorada
        console_frame = ttk.LabelFrame(self.main_frame, text="Consola de proceso", padding=10)
        console_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        self.console = ConsoleOutput(
            console_frame,
            wrap=tk.WORD,
            background='#1E1E1E',  # Fondo más suave
            foreground='#00FF00',  # Verde más brillante
            font=('Consolas', 10),
            height=15
        )
        self.console.pack(fill=tk.BOTH, expand=True)

        # Scrollbar para la consola
        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", command=self.console.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.console.configure(yscrollcommand=scrollbar.set)

        sys.stdout = self.console

        # Historial de ejecuciones
        self.history_frame = ttk.LabelFrame(self.main_frame, text="Historial de Ejecuciones", padding=10)
        self.history_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.history_text = tk.Text(
            self.history_frame,
            wrap=tk.WORD,
            background='#1E1E1E',
            foreground='#00FF00',
            font=('Consolas', 10),
            height=5
        )
        self.history_text.pack(fill=tk.BOTH, expand=True)
        self.history_text.config(state=tk.DISABLED)

        # Etiqueta del autor
        self.author_label = ttk.Label(
            self.main_frame,
            text="Creado por Ricardo Fernández",
            font=('Helvetica', 10, 'italic'),
            foreground=text_color
        )
        self.author_label.pack(side=tk.BOTTOM, pady=5) # Etiqueta del autor

        self.load_history()

    def open_dashboard(self):
       #  Dashboard.html ahora está en la misma carpeta que el script
        v22_html_path = os.path.join(script_dir, 'Dashboard.html')
        webbrowser.open_new(v22_html_path)

    def mostrar_info(self):
        info_window = tk.Toplevel(self.root)
        info_window.title("Información del Script")
        info_window.geometry("600x450")
        info_window.configure(bg="#2b2b2b")

        info_text = """
        Este script automatiza la validación de CUITs de clientes
        utilizando las APIs de Tango Gestión y Arca .

        Objetivo:
        - Obtener la lista de clientes de Tango Gestión con la api.
        - Filtrar los clientes que cumplan con ciertas condiciones.
        - Validar el CUIT de cada cliente con la API de Mr. Bot con Arca (Ex Afip).
        - Generar un reporte en Excel con los clientes que presenten
          problemas en la validación.

        Funcionamiento:
        1. Se conecta a la API de Tango Gestión para obtener la lista de clientes.
        2. Filtra los clientes según las condiciones especificadas.
        3. Itera sobre la lista de clientes filtrados y valida cada CUIT con la API de Mr. Bot con Arca (Ex Afip) 
        """

        # Crear un Text widget para mostrar la información
        info_text_widget = tk.Text(
            info_window,
            font=('Helvetica', 10),
            wrap=tk.WORD,
            bg="#2b2b2b",
            fg="#e5e8e8",
            padx=10,
            pady=10
        )
        info_text_widget.pack(fill=tk.BOTH, expand=True)

        # Insertar el texto informativo
        info_text_widget.insert(tk.END, info_text)

        # Añadir enlaces clickeables
        link1 = "https://api-constancias-de-inscripcion.mrbot.com.ar/docs#/default/root__get"


        link2 = "https://ayudas.axoft.com/23ar/documentos/operacion/apertura_oper/api_oper/"

        info_text_widget.insert(tk.END, "\n\nEnlaces:\n")
        info_text_widget.insert(tk.END, link1 + "\n", "link")
        info_text_widget.insert(tk.END, link2, "link")

        # Configurar las etiquetas de los enlaces
        info_text_widget.tag_config("link", foreground="blue", underline=1)
        info_text_widget.tag_bind("link", "<Button-1>", lambda e, url=link1: self.open_link(url))
        info_text_widget.tag_bind("link", "<Button-1>", lambda e, url=link2: self.open_link(url), add=True)

        # Deshabilitar la edición del Text widget
        info_text_widget.config(state=tk.DISABLED)

    def open_link(self, url):
        webbrowser.open_new(url)

    def print_console(self, message):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}")

    def select_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.output_path.set(directory)
            self.start_button.config(state=tk.NORMAL)

    def iniciar_proceso_thread(self):
        if not self.output_path.get() or self.output_path.get() == "Seleccione directorio de salida...":
            self.print_console("Error: Por favor seleccione un directorio de salida")
            return
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.stop_event.clear()
        Thread(target=self.iniciar_proceso, daemon=True).start()

    def stop_proceso(self):
        self.stop_event.set()
        self.stop_button.config(state=tk.DISABLED)
        self.start_button.config(state=tk.NORMAL)
        self.actualizar_estado("Proceso detenido")
        self.print_console("Proceso detenido por el usuario.")

    def iniciar_proceso(self):
        try:
            if not self.output_path.get() or self.output_path.get() == "Seleccione directorio de salida...":
                self.print_console("Error: Por favor seleccione un directorio de salida")
                return

            self.actualizar_estado("Iniciando proceso...")
            self.print_console("Iniciando agente Tango-AFIP")

            # Validar claves de API
            self.print_console("Validando claves de API...")
            if not TANGO_API_TOKEN or not TANGO_COMPANY_ID or not AFIP_USER or not AFIP_API_KEY:
                self.print_console("Error: Las claves de API no están configuradas correctamente.")
                self.actualizar_estado("Error en la configuración")
                return

            # Obtener clientes
            self.print_console("Conectando con API de Tango...")
            clientes_tango = []
            total_pages = obtener_paginacion_tango(process="2117")
            if total_pages == 0:
                self.print_console("Error al obtener el número de páginas de la API de Tango.")
                self.actualizar_estado("Error al obtener datos de Tango")
                return

            for page_index in range(total_pages):
                if self.stop_event.is_set():
                    break
                self.print_console(f"Obteniendo página {page_index + 1}/{total_pages} de clientes...")
                clientes_pagina = obtener_datos_tango(process="2117", page_index=page_index)
                if not clientes_pagina:
                    break
                clientes_tango.extend(clientes_pagina)

            self.print_console(f"Total de clientes obtenidos: {len(clientes_tango)}")

            # Filtrar clientes
            self.actualizar_estado("Filtrando clientes...")
            clientes_filtrados = filtrar_clientes(clientes_tango)
            self.print_console(f"Clientes filtrados: {len(clientes_filtrados)}")

            self.progress["maximum"] = len(clientes_filtrados)

            # Validar CUITS
            resultados_validacion = []
            
            for i, cliente in enumerate(clientes_filtrados):
                if self.stop_event.is_set():
                    break
                cod_gva14 = cliente.get("COD_GVA14", "N/A")
                razon_social = cliente.get("RAZON_SOCI", "N/A")
                cuit = cliente.get("CUIT", "")

                self.actualizar_estado(f"Validando CUIT {i + 1}/{len(clientes_filtrados)}")
                self.print_console(f"Procesando: {razon_social} - CUIT: {cuit}")

                cuit_limpio = cuit.replace("-", "").replace(" ", "")

                if not cuit_limpio:
                    continue
                if not es_cuit_valido(cuit_limpio):
                    self.print_console(f"Error: CUIT inválido para {razon_social}: {cuit_limpio}")
                    resultados_validacion.append({
                        "Código de Cliente": cod_gva14,
                        "RAZON_SOCI": razon_social,
                        "Cuit": cuit,
                        "Detalles de la Baja": "CUIT con formato inválido"
                         })
                    self.progress["value"] = i + 1
                    self.root.update() 
                    continue

                try:
                    resultado_api = validar_cuit_afip(int(cuit_limpio))
                    if resultado_api is None:
                        continue

                    error = resultado_api.get("errorConstancia", {}).get("error", [])
                    if error:
                       resultados_validacion.append({
                            "Código de Cliente": cod_gva14,
                            "RAZON_SOCI": razon_social,
                            "Cuit": cuit,
                            "Detalles de la Baja": ", ".join(error)
                         })
                    else:
                           resultados_validacion.append({
                            "Código de Cliente": cod_gva14,
                            "RAZON_SOCI": razon_social,
                            "Cuit": cuit,
                            "Detalles de la Baja": "Sin errores"
                         })

                except ValueError:
                    self.print_console(f"Error: CUIT inválido para {razon_social}")
                except Exception as e:
                    self.print_console(f"Error procesando cliente {razon_social}: {str(e)}")
                self.progress["value"] = i + 1
                self.root.update()  # Actualizar la interfaz para mostrar el progreso

            # Generar Excel en el directorio seleccionado
            clientes_con_problemas = [r for r in resultados_validacion if r['Detalles de la Baja'] != "Sin errores"]
            if clientes_con_problemas:
                self.actualizar_estado("Generando archivo Excel...")
                df = pd.DataFrame(clientes_con_problemas)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                archivo_excel = os.path.join(self.output_path.get(), f"reporte_afip_errores_{timestamp}.xlsx")
                try:
                    with pd.ExcelWriter(archivo_excel) as writer:
                        df.to_excel(writer, sheet_name='Clientes Invalidos', index=False)
                    self.print_console(f"Archivo Excel generado: {archivo_excel}")
                     # Generar datos para el dashboard y actualizar v22.html
                    chart_data_path = os.path.join(script_dir, 'chart_data.json')
                    v22_html_path = os.path.join(script_dir, 'Dashboard.html')
                    
                    #Pasar el dataframe a la funcion en analisis_avanzado
                    analisis_avanzado.process_data_for_chartjs(df,chart_data_path)


                    with open(chart_data_path, 'r') as f:
                        chart_data = json.load(f)
                    with open(v22_html_path, 'r') as html_file:
                        html_content = html_file.read()

                    new_html_content = html_content.replace('// Datos para Chart.js', f'const chartData = {json.dumps(chart_data)};')
                    with open(v22_html_path, 'w') as html_file:
                        html_file.write(new_html_content)

                except (FileNotFoundError, json.JSONDecodeError, KeyError, IOError, Exception) as e:
                     self.print_console(f"Error al procesar datos para gráficos o actualizar v22.html: {e}")
                     self.actualizar_estado(f"Error: {e}")
            else:
                 self.print_console("No se encontraron clientes con errores. No se generó el archivo Excel.")

            # Generar reporte visual
            self.root.after(0, lambda: generar_reporte_visual(resultados_validacion))

            # Guardar un excel con los resultados totales
            if resultados_validacion:
                self.actualizar_estado("Generando Archivo Excel de Resultados...")
                df = pd.DataFrame(resultados_validacion)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                archivo_excel_completo = os.path.join(self.output_path.get(), f"reporte_total_{timestamp}.xlsx")
                try:
                    with pd.ExcelWriter(archivo_excel_completo) as writer:
                         df_validos = df[df["Detalles de la Baja"] == "Sin errores"]
                         df_invalidos = df[df["Detalles de la Baja"] != "Sin errores"]
                         df_validos.to_excel(writer, sheet_name="Clientes Validos", index=False)
                         df_invalidos.to_excel(writer, sheet_name="Clientes Invalidos", index=False)
                    self.print_console(f"Archivo Excel total generado: {archivo_excel_completo}")
                except Exception as e:
                    self.print_console(f"Error al generar el archivo Excel total: {e}")

            self.actualizar_estado("Proceso completado")
            self.print_console("Proceso finalizado exitosamente")
            self.mostrar_notificacion_fin()
            self.save_history(len(clientes_filtrados), resultados_validacion)

        except Exception as e:
            self.print_console(f"Error: {str(e)}")
            self.actualizar_estado("Error en el proceso")
        finally:
            self.start_button.configure(state='normal')
            self.stop_button.config(state=tk.DISABLED)

    def actualizar_estado(self, mensaje):
        self.status_label.config(text=f"Estado: {mensaje}")
        self.root.update()

    def configure_styles(self, bg_color, text_color, button_color, progress_color):
        """Configura los estilos personalizados para los widgets."""
        style = ttk.Style()
        style.theme_use("clam")

        # Estilo para botones
        style.configure(
            "Custom.TButton",
            background=button_color,
            foreground=text_color,
            padding=5,
            font=("Helvetica", 12)
        )
        style.map(
            "Custom.TButton",
            background=[("active", button_color)]
        )

        # Estilo para la barra de progreso
        style.configure(
            "Custom.Horizontal.TProgressbar",
            background=progress_color,
            troughcolor=bg_color
        )

        # Estilo para las entradas
        style.configure(
            "Custom.TEntry",
            fieldbackground=bg_color,
            foreground=text_color,
            insertcolor=text_color
        )

        # Estilo para los frames
        style.configure(
            "Custom.TFrame",
            background=bg_color
        )

        # Estilo para los LabelFrames
        style.configure(
            "Custom.TLabelframe",
            background=bg_color,
            foreground=text_color
        )

    def exportar_log(self):
        log_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if log_path:
            with open(log_path, "w") as log_file:
                with open(log_filename, "r") as src:
                    log_file.write(src.read())
            self.print_console(f"Log exportado a: {log_path}")

    def mostrar_notificacion_fin(self):
        messagebox.showinfo("Proceso completado", "La validación de CUIT ha finalizado exitosamente.")

    def save_history(self, clientes_validados, resultados_validacion):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_entry = f"{timestamp} - Clientes validados: {clientes_validados}, Resultados: {len(resultados_validacion)}\n"
        with open("history.txt", "a") as f:
            f.write(history_entry)
        self.load_history()

    def load_history(self):
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete("1.0", tk.END)
        try:
            with open("history.txt", "r") as f:
                history = f.read()
                self.history_text.insert(tk.END, history)
        except FileNotFoundError:
            pass
        self.history_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = ModernApp(root)
    root.mainloop()
