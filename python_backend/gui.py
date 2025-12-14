import tkinter as tk
from tkinter import ttk, messagebox
import requests
import json


class BotGUI:
    """Interfaz gráfica simple para configurar el bot"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🤖 Configuración del Bot")
        self.root.geometry("600x400")
        self.root.minsize(500, 350)

        # Cargar configuración inicial
        self.respuesta_actual = self.obtener_respuesta_actual()

        self.crear_interfaz()

    def obtener_respuesta_actual(self):
        """Obtiene la respuesta actual del servidor"""
        try:
            response = requests.get("http://localhost:5001/config", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get("respuesta_bot", "Hola, soy un bot 🤖")
        except:
            pass
        return "Hola, soy un bot 🤖"

    def crear_interfaz(self):
        """Crea la interfaz gráfica"""
        # Frame principal
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Título
        title_label = ttk.Label(
            main_frame,
            text="Configuración del Bot WhatsApp",
            font=("Arial", 16, "bold")
        )
        title_label.pack(pady=(0, 20))

        # Frame para la respuesta
        resp_frame = ttk.LabelFrame(main_frame, text="Respuesta del Bot", padding=15)
        resp_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))

        # Texto explicativo
        ttk.Label(
            resp_frame,
            text="Configura el mensaje que responderá el bot cuando alguien escriba 'hola':",
            font=("Arial", 10)
        ).pack(anchor="w", pady=(0, 10))

        # Área de texto para la respuesta
        self.text_area = tk.Text(
            resp_frame,
            height=8,
            font=("Arial", 10),
            wrap=tk.WORD
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)

        # Insertar respuesta actual
        self.text_area.insert("1.0", self.respuesta_actual)

        # Frame para botones
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        # Botón Guardar
        save_button = ttk.Button(
            button_frame,
            text="💾 Guardar Respuesta",
            command=self.guardar_respuesta
        )
        save_button.pack(side=tk.LEFT, padx=(0, 10))

        # Botón Probar
        test_button = ttk.Button(
            button_frame,
            text="🔊 Probar Respuesta",
            command=self.probar_respuesta
        )
        test_button.pack(side=tk.LEFT, padx=10)

        # Botón Salir
        exit_button = ttk.Button(
            button_frame,
            text="❌ Salir",
            command=self.root.quit
        )
        exit_button.pack(side=tk.RIGHT)

        # Estado
        self.status_label = ttk.Label(
            main_frame,
            text="Estado: Listo",
            font=("Arial", 9)
        )
        self.status_label.pack(pady=(10, 0))

    def guardar_respuesta(self):
        """Guarda la respuesta en el servidor"""
        respuesta = self.text_area.get("1.0", tk.END).strip()

        if not respuesta:
            messagebox.showwarning("Advertencia", "La respuesta no puede estar vacía")
            return

        try:
            # Enviar al servidor
            response = requests.post(
                "http://localhost:5001/config",
                json={"respuesta_bot": respuesta},
                timeout=5
            )

            if response.status_code == 200:
                self.status_label.config(text="✅ Respuesta guardada correctamente")
                messagebox.showinfo("Éxito", "Respuesta guardada correctamente")
            else:
                error_msg = response.json().get("error", "Error desconocido")
                self.status_label.config(text=f"❌ Error: {error_msg}")
                messagebox.showerror("Error", f"No se pudo guardar: {error_msg}")

        except requests.exceptions.ConnectionError:
            self.status_label.config(text="❌ No se puede conectar al servidor")
            messagebox.showerror("Error de conexión",
                                 "No se puede conectar al servidor Flask.\n"
                                 "Asegúrate de que esté ejecutándose en el puerto 5001.")
        except Exception as e:
            self.status_label.config(text=f"❌ Error: {str(e)}")
            messagebox.showerror("Error", f"Error inesperado: {str(e)}")

    def probar_respuesta(self):
        """Muestra una vista previa de la respuesta"""
        respuesta = self.text_area.get("1.0", tk.END).strip()

        if not respuesta:
            messagebox.showwarning("Advertencia", "No hay respuesta para probar")
            return

        # Crear ventana de vista previa
        preview = tk.Toplevel(self.root)
        preview.title("Vista Previa")
        preview.geometry("400x300")

        ttk.Label(
            preview,
            text="Así verá el usuario tu respuesta:",
            font=("Arial", 11, "bold")
        ).pack(pady=10)

        # Frame con estilo de chat
        chat_frame = ttk.Frame(preview, relief=tk.RIDGE, borderwidth=2)
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Texto de respuesta (simulando chat de WhatsApp)
        text_widget = tk.Text(
            chat_frame,
            height=10,
            font=("Arial", 10),
            wrap=tk.WORD,
            bg="#e1ffc7",  # Color similar a WhatsApp
            relief=tk.FLAT,
            padx=10,
            pady=10
        )
        text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        text_widget.insert("1.0", respuesta)
        text_widget.config(state=tk.DISABLED)

        # Botón cerrar
        ttk.Button(
            preview,
            text="Cerrar",
            command=preview.destroy
        ).pack(pady=10)

    def run(self):
        """Inicia la interfaz gráfica"""
        self.root.mainloop()


# Para ejecutar directamente
if __name__ == "__main__":
    app = BotGUI()
    app.run()