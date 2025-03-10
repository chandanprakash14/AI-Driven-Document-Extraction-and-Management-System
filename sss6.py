from flask import Flask, request, jsonify, render_template, redirect, url_for
import google.generativeai as genai
from PIL import Image
import pytesseract
from pymongo import MongoClient
import os
import json
from werkzeug.utils import secure_filename
from bson import ObjectId  # Import ObjectId for MongoDB

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Ensure uploads folder exists
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

genai.configure(api_key="AIzaSyD0nd00vnh2sZLPVprzTDxe0Pi6IxwkrP4")
model = genai.GenerativeModel("gemini-1.5-flash")

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["text_extract"]
collection = db["posts"]

@app.route("/", methods=["GET"])
def index():
    return render_template("upload.html")

@app.route("/search", methods=["GET", "POST"])
def search_record():
    if request.method == "POST":
        try:
            search_query = request.form.get("search_query", "").strip()
            if not search_query:
                return jsonify({"error": "Please provide a keyword to search"}), 400

            query = {"$or": [
                {key: {"$regex": search_query, "$options": "i"}}
                for key in ["company_name", "name", "profession", "email", "address", "phone_number", "website"]
            ]}
            results = collection.find(query)
            results_list = [
                {**doc, "_id": str(doc["_id"])} for doc in results
            ]  # Convert ObjectId to string for all results

            if not results_list:
                return render_template("results.html", data=None)

            return render_template("results.html", data=results_list)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return render_template("search.html")

@app.route("/upload", methods=["POST"])
def upload_images():
    try:
        if "images" not in request.files:
            return jsonify({"error": "No images provided"}), 400

        uploaded_images = request.files.getlist("images")
        if not uploaded_images:
            return jsonify({"error": "No images uploaded"}), 400

        image_dict = {}
        results = []

        # Group images by base name to identify pairs
        for img_file in uploaded_images:
            filename = secure_filename(img_file.filename)
            base_name = os.path.splitext(filename)[0]  # Get name without extension
            if "_img1" in base_name or "_img2" in base_name:  # Check for pair
                pair_key = base_name.replace("_img1", "").replace("_img2", "")
                if pair_key not in image_dict:
                    image_dict[pair_key] = []
                image_dict[pair_key].append(img_file)
            else:
                # Handle single images
                if base_name not in image_dict:
                    image_dict[base_name] = []
                image_dict[base_name].append(img_file)

        # Process grouped images
        for key, img_files in image_dict.items():
            texts = []
            filenames = []

            for img_file in img_files:
                try:
                    img = Image.open(img_file)
                    text = pytesseract.image_to_string(img)
                    texts.append(text)

                    # Save the image with unique naming
                    original_filename = secure_filename(img_file.filename)
                    new_filename = f"{key}_{len(filenames) + 1}.jpg"
                    save_path = os.path.join(app.config["UPLOAD_FOLDER"], new_filename)

                    # Convert to RGB if needed and save
                    if img.mode == "RGBA":
                        img = img.convert("RGB")
                    img.save(save_path)
                    filenames.append(new_filename)
                except Exception as e:
                    return jsonify({"error": f"Error processing image {img_file.filename}: {str(e)}"}), 500

            # Generate combined response using the generative model
            try:
                response = model.generate_content(
                    [
                        "Combine the information from the following images. Extract the company name, name, profession, "
                        "email address, address, phone number, and website. Provide the output in JSON format. "
                        "Don't provide the unwanted string, Provide only json.",
                        *texts,
                    ]
                )
                js = response.text.strip().replace("```json", "").replace("```", "")
                data = json.loads(js)
                data["files"] = filenames

                # Save to MongoDB and handle ObjectId serialization
                inserted_id = collection.insert_one(data).inserted_id
                data["_id"] = str(inserted_id)  # Convert ObjectId to string
                results.append(data)
            except json.JSONDecodeError:
                return jsonify({"error": "Failed to parse the response. Ensure the model output is in JSON format."}), 500
            except Exception as e:
                return jsonify({"error": f"Error with generative model: {str(e)}"}), 500

        return jsonify({"success": True, "results": results}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
