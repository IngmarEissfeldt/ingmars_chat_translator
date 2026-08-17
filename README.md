# Ingmars Chat Translator

## [How to use the app](https://ingmareissfeldt.github.io/ingmars_chat_translator/translator_tutorial_v1.pdf)

## To recreate the environment
Clone the project with `git clone https://github.com/IngmarEissfeldt/ingmars_chat_translator.git`

Go into the cloned project folder with `cd ingmars_chat_translator`

Create your environment with `python -m venv translator-env`

Activate the environment with `translator-env\Scripts\activate`

Inside the environment install the dependencies with `python -m pip install -r requirements.txt`


## AI disclaimer:
The live translation uses Gemini AI, and you are required to make an API key on the aistudio.google.com website to use the app. However you are not requested to set up billing, this app is intended to be used for free.
The python files 'overlay.py', 'key_handler.py' and 'ocr_sort.py' are written by AI, as well as the function 'set_region' in 'main.py'.
'overlay.py' uses the win32api python library, and learning to use it myself would have added probably 20 hours of development time.
'key_handler.py' handles the users API key, which I have not properly investigated, however upon review of the generated code and its function I deem it to be good enough, especially since the user isn't supposed to set up billing for their API key anyways.
'ocr_sort.py' turned out to be so much more complicated than I thought, and I was tired and wanted to get a working 'version 1' out, so I decided to generate it.
similarly to 'overlay.py', 'set_region' uses some advanced tkinter shenanigans which would've added like an hour of development time.

However 90% of main.py is written by hand by myself, and I thought of all the architecture and structure of the program myself.
