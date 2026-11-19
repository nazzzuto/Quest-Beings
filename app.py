from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home(): 
    challenge = {
        "title": "AWS Cloud Quiz",
        "description": "Answer 5 questions as fast as you can. Speed earns bonus points.",
        "seconds_left": 600,
    }
    players = [
        {"name": "Rahath", "score": 120},
        {"name": "Prasurjya", "score": 95},
        {"name": "Nazath", "score": 80},
    ]

    return render_template("home.html", challenge=challenge, players=players)

if __name__ == "__main__":
    app.run(debug=True)