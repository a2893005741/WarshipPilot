from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new("RGBA", (256, 256))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((4, 4, 252, 252), radius=52, fill="#112b3a")
draw.line([(43, 79), (82, 175), (128, 108), (174, 175), (213, 79)], fill="#8de0d4", width=16, joint="curve")
draw.line([(54, 205), (202, 205)], fill="#547a87", width=5)
image.save(Path(__file__).resolve().parent.parent / "assets" / "app.ico", sizes=[(32,32),(48,48),(64,64),(128,128),(256,256)])
