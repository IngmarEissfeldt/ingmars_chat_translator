import numpy as np
import dxcam
from PIL import Image, ImageTk, ImageDraw
import tkinter as tk
from tkinter import ttk
import easyocr
from google import genai
from pathlib import Path
import ast
from overlay import Overlay
from pynput import keyboard
import keyring
import os
from key_handler import ApiKeyDialog
import time
import threading
from ocr_sort import sort_chat_text



class ChatTranslator(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Chat Translator")
        self.starting_window_width = 400
        self.starting_window_height = 170
        self.geometry(str(self.starting_window_width)+"x"+str(self.starting_window_height))
        self.minsize(self.starting_window_width, self.starting_window_height)
        self.resizable(False, False)
        self.grid_columnconfigure(0, weight=1, minsize=110)
        self.grid_columnconfigure(1, weight=1, minsize=100)
        self.grid_columnconfigure(2, weight=1, minsize=110)

        self.overlay = Overlay()
        self.overlay.show()
        self.is_overlay_toggled = True

        self.translation_loop_running = False
        self.raw_chat_log = []
        self.trans_chat_log = []
        self.chat_pos = []

        self.appdata = Path.home() / "AppData" / "Local" / "IngmarsChatTranslator"

        self.is_toggeling_via_keyboard = False
        self.listener = keyboard.Listener(
            on_press=self.on_key_press
        )
        self.listener.start()

        self.make_settings_folder()
        self.settings = ["", ""]
        self.load_settings() # 0: Last used target language; 1: Toggle text keybind (WIP)

        self.current_region = None
        self.region_list = []
        self.load_presets()

        self.target_language = self.settings[0]
        self.current_script = []
        self.script_list = {
            "Latin": [
                'af', 'az', 'bs', 'cs', 'cy', 'da', 'de', 'en', 'es', 'et',
                'fr', 'ga', 'hr', 'hu', 'id', 'is', 'it', 'ku', 'la', 'lt',
                'lv', 'mi', 'ms', 'mt', 'nl', 'no', 'oc', 'pi', 'pl', 'pt',
                'ro', 'rs_latin', 'sk', 'sl', 'sq', 'sv', 'sw', 'tl', 'tr',
                'uz', 'vi'
            ],
            "Simplified_Chinese": ['ch_sim', 'en'],
            "Traditional_Chinese": ['ch_tra', 'en'] ,
            "Japanese": ['ja', 'en'],
            "Korean": ['ko', 'en'],
            "Cyrillic": [
                'ru', 'rs_cyrillic', 'be', 'bg', 'uk', 'mn',
                'abq', 'ady', 'kbd', 'ava', 'dar', 'inh', 'che',
                'lbe', 'lez', 'tab', 'tjk', 'en'
            ],
            "Arabic": [
                'ar', 'fa', 'ug', 'ur', 'en'
            ],
            "Devanagari": [
                'hi', 'mr', 'ne', 'bh', 'mai', 'ang', 'bho', 'mah',
                'sck', 'new', 'gom', 'sa', 'bgc', 'en'
            ],
            "Bengali": [
                'bn', 'as', 'mni', 'en'
            ],
            "Thai": ['th', 'en'],
            "Tamil": ['ta', 'en'],
            "Telugu": ['te', 'en'],
            "Kannada": ['kn', 'en']
            }
        self.reader = easyocr.Reader(['en'])

        self.api_key = self.get_api_key()
        if not self.api_key:
            self.ask_for_api_key()
        self.client = genai.Client(api_key=self.api_key)

        self.camera = dxcam.create(
            backend="dxgi", # default Desktop Duplication backend
            processor_backend="cv2" # default OpenCV processor
        )
        self.frame = None
        self.photo = None

        self.chat_toggle = True


        self.set_region_button = tk.Button(self, text="Set chat region", command=self.select_region_countdown)
        self.set_region_button.grid(row=0, column=0)

        self.region_name_entry = tk.Entry(self)
        self.region_name_entry.grid(row=1, column=0)

        self.save_region_button = tk.Button(self, text="Save chat region", command=self.save_region)
        self.save_region_button.grid(row=2, column=0)

        self.select_preset_region_label = tk.Label(self, text="Select preset region")
        self.select_preset_region_label.grid(row=3, column=0)

        self.preset_region_selector = ttk.Combobox(
            self,
            values=[i[0] for i in self.region_list],
            state="readonly"
        )
        self.preset_region_selector.bind(
            "<<ComboboxSelected>>",
            self.set_preset_region
        )
        self.preset_region_selector.grid(row=4, column=0)

        self.delete_preset_button = tk.Button(self, text="Delete preset", command=self.delete_preset)
        self.delete_preset_button.grid(row=5, column=0)


        self.start_translating_toggle = ttk.Button(
            self,
            text="Start translating",
            command=self.toggle_translation_loop
        )
        self.start_translating_toggle.grid(row=0,  column=1)

        self.toggle_hotkeys_button = tk.Button(self, text="Toggle hotkeys", command=self.toggle_hotkeys)
        self.toggle_hotkeys_button.grid(row=2, column=1)

        self.toggle_text_vis_button = tk.Button(self, text="Toggle Text", command=self.enter_pressed)
        self.toggle_text_vis_button.grid(row=3, column=1)

        self.clear_translation_button = tk.Button(self, text="Clear Text", command=self.clear_translation)
        self.clear_translation_button.grid(row=4, column=1)

        self.log_label = tk.Label(self, text="Event Log")
        self.log_label.grid(row=5, column=1)

        self.photo_label = tk.Label(self, image=self.photo)


        self.select_script_label = tk.Label(self, text="Select Script")
        self.select_script_label.grid(row=0, column=2)

        self.script_selector = ttk.Combobox(
            self,
            values=[i for i in self.script_list],
            state="readonly"
        )
        self.script_selector.bind(
            "<<ComboboxSelected>>",
            self.set_script
        )
        self.script_selector.current(0)
        self.script_selector.grid(row=1, column=2)

        self.select_target_label = tk.Label(self, text="Target language")
        self.select_target_label.grid(row=2, column=2)

        self.target_language_entry = tk.Entry(self)
        self.target_language_entry.grid(row=3, column=2)

        self.target_language_button = tk.Button(self, text="Set target language", command=self.set_target_language)
        self.target_language_button.grid(row=4, column=2)

        self.current_target_label = tk.Label(self, text="Target language: \n" + self.target_language)
        self.current_target_label.grid(row=5, column=2)


        self.update_idletasks()
        self.photo_label.place(relx=0.5, y=self.grid_bbox(row=0, column=0, row2=5, col2=2)[3], anchor="n")


    
    def ask_for_api_key(self):
        dialog = ApiKeyDialog(self)
        self.wait_window(dialog)

        self.api_key = dialog.result

        if not self.api_key:
            self.destroy()

    def get_api_key(self):
        # First try your development environment variable
        api_key = os.getenv("GEMINI_API_KEY")

        if api_key:
            return api_key

        # Otherwise get the user's saved key
        return keyring.get_password(
            "ChatTranslator",
            "gemini_api_key"
        )

    def toggle_hotkeys(self):
        self.is_toggeling_via_keyboard = not self.is_toggeling_via_keyboard


    def make_settings_folder(self):
        if not self.appdata.exists():
            self.appdata.mkdir(parents=True, exist_ok=True)

    def load_presets(self):
        path_to_presets = self.appdata / "presets.txt"
        if path_to_presets.exists():
            self.region_list = ast.literal_eval(path_to_presets.read_text(encoding="utf-8"))

    def load_settings(self):
        path_to_settings = self.appdata / "settings.txt"
        if path_to_settings.exists():
            self.settings = ast.literal_eval(path_to_settings.read_text(encoding="utf-8"))

    
    def on_key_press(self, key):
        if self.is_toggeling_via_keyboard:
            if key == keyboard.Key.enter:
                # Don't modify Tkinter widgets directly from
                # the pynput thread.
                self.after(0, self.enter_pressed)
            elif key == keyboard.Key.esc and self.is_overlay_toggled == True:
                self.after(0, self.enter_pressed)

    def enter_pressed(self):
        self.is_overlay_toggled = not self.is_overlay_toggled
        self.overlay.toggle()


    def select_region_countdown(self, count=3):
        if count > 0:
            self.set_region_button.config(text=str(count))
            self.after(1000, lambda: self.select_region_countdown(count - 1))
        else:
            self.set_region_button.config(text="Selecting region")
            self.select_region()
            self.set_region_button.config(text="Set selected region")


    def select_region(self): #made by AI
        root = tk.Toplevel(self)

        # Fullscreen window
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)

        # Make the window transparent
        root.attributes("-alpha", 0.3)

        canvas = tk.Canvas(root, cursor="cross")
        canvas.pack(fill="both", expand=True)

        start_x = start_y = 0
        rectangle = None
        result = None

        def mouse_down(event):
            nonlocal start_x, start_y, rectangle

            start_x = event.x
            start_y = event.y

            rectangle = canvas.create_rectangle(
                start_x, start_y,
                start_x, start_y,
                outline="red",
                width=2
            )

        def mouse_drag(event):
            canvas.coords(
                rectangle,
                start_x, start_y,
                event.x, event.y
            )

        def mouse_up(event):
            nonlocal result

            result = (
                min(start_x, event.x),
                min(start_y, event.y),
                max(start_x, event.x),
                max(start_y, event.y)
            )

            root.destroy()


        canvas.bind("<ButtonPress-1>", mouse_down)
        canvas.bind("<B1-Motion>", mouse_drag)
        canvas.bind("<ButtonRelease-1>", mouse_up)

        self.wait_window(root)

        self.current_region = result

        self.preset_region_selector.set("")
        self.render_scr()
        self.set_log("New region set")



    def set_preset_region(self, event):
        self.current_region = [i[1] for i in self.region_list if i[0] == self.preset_region_selector.get()][0] # compares the region names to the selected name and only picks the one that's selected
        self.render_scr()
        self.set_log("Loaded preset: " + str(self.preset_region_selector.get()))

    def set_script(self, event):
        self.current_script = self.script_list[self.script_selector.get()]
        self.reader = easyocr.Reader(self.current_script)

    def set_target_language(self):
        if self.target_language_entry.get() != "":
            self.target_language = self.target_language_entry.get()
            self.current_target_label.config(text="Target language: " + self.target_language)

            self.settings[0] = self.target_language
            path_to_settings = self.appdata / "settings.txt"
            with open(path_to_settings, "w", encoding="utf-8") as f:
                f.write(str(self.settings))

    def set_log(self, text):
        self.after(0, lambda: self.log_label.config(text=text))

    def clear_translation(self):
        self.overlay.clear()
        self.raw_chat_log.clear()
        self.render_scr()
        self.set_log("Text cleared")

    def delete_preset(self):
        self.region_list = [i for i in self.region_list if i[0] != self.preset_region_selector.get()]
        path_to_presets = self.appdata / "presets.txt"
        with open(path_to_presets, "w", encoding="utf-8") as f:
            f.write(str(self.region_list))
        self.preset_region_selector.set("")
        self.preset_region_selector.config(values=[i[0] for i in self.region_list])
        self.photo_label.config(image=None)
        self.set_log("Preset deleted")


    def save_region(self):
        if self.region_name_entry.get() == "":
            self.save_region_button.config(text="Please provide a name for the preset,\n like a game or app name")

            self.after(2000, lambda: self.save_region_button.config(text="Save chat region"))

        elif self.current_region == None:
            self.save_region_button.config(text="Please select a chat region")
            
            self.after(2000, lambda: self.save_region_button.config(text="Save chat region"))

        else:
            region_name = self.region_name_entry.get()

            self.region_list = [i for i in self.region_list if i[0] != region_name] #replaces region list with itself except for the to be saved region

            self.region_list.append((region_name, self.current_region))

            path_to_presets = self.appdata / "presets.txt"
            with open(path_to_presets, "w", encoding="utf-8") as f:
                f.write(str(self.region_list))

            self.load_presets()

            self.preset_region_selector.config(values=[i[0] for i in self.region_list])

            self.save_region_button.config(text="Saved!")
            self.after(1000, lambda: self.save_region_button.config(text="Save chat region"))


    def get_scr(self, max_retries=600, delay=1): #Written by AI, my own version was kind of shit
        for _ in range(max_retries):
            self.frame = self.camera.grab(region=self.current_region)
            if isinstance(self.frame, np.ndarray):
                return self.frame
            self.set_log("Retrying screenshot")
            time.sleep(delay)
        raise RuntimeError("Failed to grab a valid frame after retries")
        
    def render_scr(self, frame=None, borders=None):
        if not isinstance(frame, np.ndarray):
            frame = self.get_scr()
        img = Image.fromarray(frame)

        if borders != None:
            draw = ImageDraw.Draw(img)
            for border in borders:
                draw.rectangle(border, outline=(255, 0, 0), width=3)

        self.photo = ImageTk.PhotoImage(img)

        self.photo_label.config(image=self.photo)

        if self.starting_window_width < self.photo.width():
            self.geometry(str(self.photo.width())+"x"+str(self.starting_window_height + self.photo.height()))
        else:
            self.geometry(str(self.starting_window_width)+"x"+str(self.starting_window_height + self.photo.height()))
        
    
    def toggle_translation_loop(self):
        self.translation_loop_running = not self.translation_loop_running

        if self.translation_loop_running:
            if self.current_region == None:
                self.start_translating_toggle.config(text="Please select a chat region!")
                self.after(2000, lambda: self.start_translating_toggle.config(text="Start translating"))
            elif self.target_language == "":
                self.start_translating_toggle.config(text="Please select a target language!")
                self.after(2000, lambda: self.start_translating_toggle.config(text="Start translating"))
            else:
                self.start_translating_toggle.config(text="Stop translating")
                self.set_log("Translation started")
                threading.Thread(target=self.trans_loop, daemon=True).start()
        else:
            self.start_translating_toggle.config(text="Start translating")
            self.set_log("Translation stopped")

    def trans_loop(self):
        if not self.translation_loop_running:
            return

        self.set_log("Taking screenshot")
        if (self.is_toggeling_via_keyboard and self.is_overlay_toggled) or not self.is_toggeling_via_keyboard:
            self.frame = self.get_scr()
            self.set_log("Screenshot taken")
        else:
            self.set_log("Chat closed, didn't screenshot")


        new_raw_text = []
        current_raw_text = []
        new_chat_pos = []
        relative_chat_pos = []

        if not isinstance(self.frame, np.ndarray):
            self.set_log("Failed to get screenshot")

        elif (self.is_toggeling_via_keyboard and self.is_overlay_toggled) or (not self.is_toggeling_via_keyboard):
            self.set_log("Checking for new text")
            reader_output = self.reader.readtext(self.frame)
            for bbox, text, confidence in reader_output:
                if text not in self.raw_chat_log:
                    new_raw_text.append(text)
                current_raw_text.append(text)
                self.raw_chat_log.append(text)

                relative_chat_pos.append([bbox[0][0], bbox[0][1], bbox[2][0], bbox[2][1]])
                screen_bbox = [bbox[0][0], bbox[0][1], bbox[2][0], bbox[2][1]]

                screen_bbox[0] += self.current_region[0]
                screen_bbox[1] += self.current_region[1]
                screen_bbox[2] += self.current_region[0]
                screen_bbox[3] += self.current_region[1]
                new_chat_pos.append(screen_bbox)

            self.render_scr(frame=self.frame, borders=relative_chat_pos)

        #print("Bounding boxes ", new_chat_pos)
        print("Raw text ", current_raw_text)

        

        translated_text_pos = []
        if new_raw_text != []:
            self.set_log("Sorting text")

            sorted_raw_text = sort_chat_text(new_chat_pos, current_raw_text)

            print("Sorted text ", sorted_raw_text)


            self.set_log("Combining text")
            combined_raw_text = []
            text_groups = []

            for idx, text_part in enumerate(sorted_raw_text):
                if ":" in text_part or not text_groups:
                    combined_raw_text.append(text_part)
                    text_groups.append([idx])
                else:
                    # continuation of the previous group
                    combined_raw_text[-1] += " " + text_part
                    text_groups[-1].append(idx)
            #text_groups = [group for group in text_groups if len(group) != 1]
            print("Combined text", combined_raw_text)

            if self.chat_toggle:
                new_raw_text = combined_raw_text

            self.set_log("Prompting LLM")
            translation_prompt = f"""The following is a short chat conversation in a videogame. Please translate the contents into the language: "{self.target_language}". 
                The text will likely be formatted in a python list, for example: ['Furret: come here', 'Furret: I need you']. 
                Remember to use " for the string when using apostrophes in the sentence. In this case please translate the individual strings, while keeping the structure of the list. 
                The text might contain numbers instead of letters, example: '5eri0u5' instead of 'serious'. Only respond with the translated text. 
                Here is the context, do not translate this: {self.trans_chat_log}. Here is the chat, please translate this: {new_raw_text}"""
            response = self.client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=translation_prompt
            )
            self.set_log("Got response")
            try:
                translated_text = ast.literal_eval(response.text)
            except Exception as error:
                print("Caught exeption: ", error)
                fixing_prompt = "This python list has a SyntaxError inside. Please change the ' as requiered. Only answer with the fixed list. Here is the list: " + response.text
                response = self.client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=fixing_prompt
                )
                translated_text = ast.literal_eval(response.text)


            print("LLM response", translated_text)


            self.set_log("Splitting and fitting text")
            new_text_parts = []
            for group_idx, group in enumerate(text_groups):
                box_length_percentage = []
                box_length = 0
                for index in group:
                    box_length += new_chat_pos[index][2] - new_chat_pos[index][0]
                for index in group:
                    box_length_percentage.append(int(((new_chat_pos[index][2] - new_chat_pos[index][0])/box_length) * 100))

                sentence_characters = len(translated_text[group_idx])

                current_text_part_index = 0
                for idx, part in enumerate(box_length_percentage):
                    current_text_part = ""
                    if part != box_length_percentage[-1]:
                        current_text_part = translated_text[group_idx][current_text_part_index:current_text_part_index+int((float(part)/100)*sentence_characters)]
                        current_text_part_index += int((float(part)/100)*sentence_characters)
                    else:
                        current_text_part = translated_text[group_idx][current_text_part_index :]
                    new_text_parts.append((group[idx], current_text_part))

            #print(new_text_parts)

            translated_text.clear()
            for part in new_text_parts:
                translated_text.insert(part[0], part[1])

            print("Split text", translated_text)


            for i in range(len(translated_text)):
                translated_text_pos.append((translated_text[i], new_chat_pos[i]))

            self.overlay.clear()

            self.set_log("Displaying text")
            for text in translated_text_pos:
                self.overlay.add_text(
                    text[0],
                    text[1][0],
                    text[1][1],
                    text[1][2],
                    text[1][3]
                )
            #print("Text displayed")



        self.after(1000, self.trans_loop)





app = ChatTranslator()
app.mainloop()
