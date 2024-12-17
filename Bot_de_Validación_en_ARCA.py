import requests
import json
import logging
import datetime
import time
import pandas as pd
import tkinter as tk
from tkinter import filedialog, ttk
from threading import Thread, Event
import queue
import sys
import os
import webbrowser

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
TANGO_API_URL = "http://server:17000/Api/Get"
AFIP_API_URL = "https://api-constancias-de-inscripcion.mrbot.com.ar/consulta_constancia/"

# Función para leer las claves desde el archivo claves.txt
def leer_claves(filepath):
    claves = {}
    with open(filepath, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            claves[key] = value
    return claves

# Leer las claves desde el archivo
claves = leer_claves(os.path.join(script_dir, 'Access_Key.txt'))

# Asignar las claves a las variables correspondientes
TANGO_API_TOKEN = claves['TANGO_API_TOKEN']
TANGO_COMPANY_ID = claves['TANGO_COMPANY_ID']
AFIP_USER = claves['AFIP_USER']
AFIP_API_KEY = claves['AFIP_API_KEY']

# Función para obtener datos de la API de Tango Gestión
def obtener_datos_tango(process, page_size=5000, page_index=0):
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
        response = requests.get(TANGO_API_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return data["resultData"]["list"]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error en la solicitud a la API de Tango: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Error al decodificar la respuesta JSON de Tango: {e}")
        return []

# Función para validar CUIT con la API de AFIP
def validar_cuit_afip(cuit):
    params = {
        "cuit": cuit,
        "usuario": AFIP_USER,
        "api_key": AFIP_API_KEY
    }
    try:
        response = requests.get(AFIP_API_URL, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al consultar la API de AFIP para el CUIT {cuit}: {e}")
        return {"error": str(e)}

# Función para filtrar clientes según condiciones
def filtrar_clientes(clientes):
    return [
        cliente for cliente in clientes
        if cliente.get("CUIT", "")
        and cliente.get("COD_GVA14", "")[-1:].upper() == "F"
        and cliente.get("HABILITADO") is True
    ]

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

        # Etiqueta del autor
        self.author_label = ttk.Label(
            self.main_frame,
            text="Creado por Ricardo Fernández",
            font=('Helvetica', 10, 'italic'),
            foreground=text_color
        )
        self.author_label.pack(side=tk.BOTTOM, pady=5) # Etiqueta del autor

    def mostrar_info(self):
        info_window = tk.Toplevel(self.root)
        info_window.title("Información del Script")
        info_window.geometry("600x450")  # Aumenté la altura para acomodar el texto adicional
        info_window.configure(bg="#2b2b2b")

        info_text = """
        Este script automatiza la validación de CUITs de clientes
        utilizando las APIs de Tango Gestión y Arca .

        Objetivo:
        - Obtener la lista de clientes de Tango Gestión con la api.
        - Filtrar los clientes que cumplan con ciertas condiciones.
        - Validar el CUIT de cada cliente con la API de Mr Robot con Arca (Ex Afip).
        - Generar un reporte en Excel con los clientes que presenten
          problemas en la validación.

        Funcionamiento:
        1. Se conecta a la API de Tango Gestión para obtener la lista de clientes.
        2. Filtra los clientes según las condiciones especificadas.
        3. Itera sobre la lista de clientes filtrados y valida cada CUIT con la API de Mr Robot con Arca (Ex Afip) 
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

            # Obtener clientes
            self.print_console("Conectando con API de Tango...")
            clientes_tango = []
            page_index = 0

            while True:
                if self.stop_event.is_set():
                    break
                self.print_console(f"Obteniendo página {page_index + 1} de clientes...")
                clientes_pagina = obtener_datos_tango(process="2117", page_index=page_index)
                if not clientes_pagina:
                    break
                clientes_tango.extend(clientes_pagina)
                page_index += 1

            self.print_console(f"Total de clientes obtenidos: {len(clientes_tango)}")

            # Filtrar clientes
            self.actualizar_estado("Filtrando clientes...")
            clientes_filtrados = filtrar_clientes(clientes_tango)
            self.print_console(f"Clientes filtrados: {len(clientes_filtrados)}")

            self.progress["maximum"] = len(clientes_filtrados)

            # Validar CUITS
            clientes_con_problemas = []
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

                try:
                    resultado_api = validar_cuit_afip(int(cuit_limpio))
                    if resultado_api is None:
                        continue

                    error = resultado_api.get("errorConstancia", {}).get("error", [])

                    if error:
                        clientes_con_problemas.append({
                            "COD_GVA14": cod_gva14,
                            "RAZON_SOCI": razon_social,
                            "Cuit": cuit,
                            "Detalles del error": ", ".join(error)
                        })

                except ValueError:
                    self.print_console(f"Error: CUIT inválido para {razon_social}")
                except Exception as e:
                    self.print_console(f"Error procesando cliente {razon_social}: {str(e)}")

                self.progress["value"] = i + 1
                self.root.update()  # Actualizar la interfaz para mostrar el progreso

            # Generar Excel en el directorio seleccionado
            if clientes_con_problemas:  # Generar reporte con solo clientes con problemas
                self.actualizar_estado("Generando archivo Excel...")
                df = pd.DataFrame(clientes_con_problemas)

                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                archivo_excel = f"{self.output_path.get()}/reporte_afip_errores_{timestamp}.xlsx"

                df.to_excel(archivo_excel, index=False)
                self.print_console(f"Archivo Excel generado: {archivo_excel}")

            self.actualizar_estado("Proceso completado")
            self.print_console("Proceso finalizado exitosamente")

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

if __name__ == "__main__":
    root = tk.Tk()
    app = ModernApp(root)
    root.mainloop()
