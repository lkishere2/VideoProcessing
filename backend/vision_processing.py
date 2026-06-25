from transformers import AutoModelForCausalLM, AutoTokenizer
from PIL import Image

moondream_model = None
moondream_tokenizer = None

def get_moondream_model():
    global moondream_model, moondream_tokenizer
    if moondream_model is None:
        print("Loading Moondream2 Model...")
        model_id = "vikhyatk/moondream2"
        moondream_tokenizer = AutoTokenizer.from_pretrained(model_id, revision="2024-05-20")
        moondream_model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True, revision="2024-05-20").to("cpu")
    return moondream_model, moondream_tokenizer

def caption_frame(image_path: str) -> str:
    model, tokenizer = get_moondream_model()
    image = Image.open(image_path)
    caption = model.answer_question(image, "Describe exactly what is happening in this scene.", tokenizer)
    return caption
