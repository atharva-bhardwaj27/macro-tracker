from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import os
import traceback

app = Flask(__name__)
CORS(app)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "123456")
DB_PORT = os.getenv("DB_PORT", "5432")

def get_db_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT
    )

def init_db():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id INT PRIMARY KEY,
                age INT,
                height_cm FLOAT,
                sex VARCHAR(10),
                goal VARCHAR(20),
                current_weight FLOAT
            );

            CREATE TABLE IF NOT EXISTS food_items (
                food_id SERIAL PRIMARY KEY,
                food_name VARCHAR(100) UNIQUE NOT NULL,
                calories_per_100g FLOAT NOT NULL,
                protein_per_100g FLOAT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_logs (
                log_id SERIAL PRIMARY KEY,
                user_id INT REFERENCES user_profile(user_id),
                log_date DATE NOT NULL,
                body_weight FLOAT
            );

            CREATE TABLE IF NOT EXISTS meals (
                meal_id SERIAL PRIMARY KEY,
                log_id INT REFERENCES daily_logs(log_id) ON DELETE CASCADE,
                food_id INT REFERENCES food_items(food_id),
                qty_grams FLOAT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workout_logs (
                workout_id SERIAL PRIMARY KEY,
                log_id INT REFERENCES daily_logs(log_id) ON DELETE CASCADE,
                exercise_name VARCHAR(100) NOT NULL,
                sets INT NOT NULL,
                reps INT NOT NULL,
                weight_kg FLOAT NOT NULL,
                calories_burned FLOAT NOT NULL
            );
        """)
        
        cursor.execute("SELECT COUNT(*) FROM food_items;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO food_items (food_name, calories_per_100g, protein_per_100g) VALUES
                ('Oats', 389.0, 16.9),
                ('Raw Paneer', 275.0, 19.0),
                ('Whole Milk (1 glass)', 60.0, 3.2),
                ('Chicken Breast', 165.0, 31.0),
                ('Boiled Eggs', 155.0, 12.6);
            """)
            
        connection.commit()
        cursor.close()
        connection.close()
    except Exception as e:
        print("DB Init Warning:", e)

init_db()

@app.route('/api/profile/<int:user_id>', methods=['GET', 'POST'])
def handle_profile(user_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        data = request.json
        age = data.get('age', 20)
        height_cm = data.get('height_cm', 175.0)
        sex = data.get('sex', 'male')
        goal = data.get('goal', 'recomposition')
        current_weight = data.get('current_weight', 75.0)

        cursor.execute("""
            INSERT INTO user_profile (user_id, age, height_cm, sex, goal, current_weight)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE 
            SET age = EXCLUDED.age, height_cm = EXCLUDED.height_cm, sex = EXCLUDED.sex, goal = EXCLUDED.goal, current_weight = EXCLUDED.current_weight;
        """, (user_id, age, height_cm, sex, goal, current_weight))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": "Profile updated successfully!"})

    cursor.execute("SELECT age, height_cm, sex, goal, current_weight FROM user_profile WHERE user_id = %s;", (user_id,))
    profile = cursor.fetchone()

    if not profile:
        cursor.execute("""
            INSERT INTO user_profile (user_id, age, height_cm, sex, goal, current_weight)
            VALUES (%s, 20, 175.0, 'male', 'recomposition', 75.0)
            ON CONFLICT (user_id) DO NOTHING;
        """, (user_id,))
        connection.commit()
        cursor.execute("SELECT age, height_cm, sex, goal, current_weight FROM user_profile WHERE user_id = %s;", (user_id,))
        profile = cursor.fetchone()

    cursor.close()
    connection.close()

    age, height_cm, sex, goal, current_weight = profile[0], float(profile[1]), profile[2], profile[3], float(profile[4])

    height_m = height_cm / 100.0
    bmi = current_weight / (height_m ** 2)
    min_healthy_weight = 18.5 * (height_m ** 2)
    max_healthy_weight = 24.9 * (height_m ** 2)
    is_healthy = min_healthy_weight <= current_weight <= max_healthy_weight

    if sex == 'male':
        bmr = (10 * current_weight) + (6.25 * height_cm) - (5 * age) + 5
    else:
        bmr = (10 * current_weight) + (6.25 * height_cm) - (5 * age) - 161

    tdee = bmr * 1.375

    if goal == 'fat_loss':
        target_net_calories = tdee - 500
    elif goal == 'muscle_gain':
        target_net_calories = tdee + 300
    else:
        target_net_calories = tdee

    target_protein = current_weight * 2.0

    return jsonify({
        "age": age,
        "height_cm": height_cm,
        "sex": sex,
        "goal": goal,
        "current_weight": current_weight,
        "bmi": round(bmi, 1),
        "min_healthy_weight": round(min_healthy_weight, 1),
        "max_healthy_weight": round(max_healthy_weight, 1),
        "is_healthy": is_healthy,
        "target_steps": 10000 if goal != 'muscle_gain' else 8000,
        "bmr": round(bmr, 0),
        "tdee": round(tdee, 0),
        "target_net_calories": round(target_net_calories, 0),
        "target_protein": round(target_protein, 0)
    })

@app.route('/api/macros/<int:user_id>', methods=['GET'])
def get_macros(user_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("SELECT log_id, log_date FROM daily_logs WHERE user_id = %s ORDER BY log_id DESC;", (user_id,))
    logs = cursor.fetchall()
    
    results = []
    for log in logs:
        log_id = log[0]
        log_date = str(log[1])
        
        cursor.execute("""
            SELECT COALESCE(SUM(m.qty_grams * f.calories_per_100g / 100.0), 0),
                   COALESCE(SUM(m.qty_grams * f.protein_per_100g / 100.0), 0)
            FROM meals m
            JOIN food_items f ON m.food_id = f.food_id
            WHERE m.log_id = %s;
        """, (log_id,))
        meal_res = cursor.fetchone()
        total_calories = float(meal_res[0])
        total_protein = float(meal_res[1])
        
        cursor.execute("""
            SELECT COALESCE(SUM(calories_burned), 0)
            FROM workout_logs
            WHERE log_id = %s;
        """, (log_id,))
        work_res = cursor.fetchone()
        exercise_burn = float(work_res[0])
        
        net_calories = total_calories - exercise_burn
        
        results.append({
            "log_id": log_id,
            "log_date": log_date,
            "exercise_calories_burned": exercise_burn,
            "total_calories": total_calories,
            "total_protein": total_protein,
            "net_calories": net_calories
        })
        
    cursor.close()
    connection.close()
    return jsonify(results)

@app.route('/api/delete_log/<int:log_id>', methods=['DELETE'])
def delete_log(log_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM daily_logs WHERE log_id = %s;", (log_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": "Log deleted successfully!"}), 200
    except Exception as error:
        if connection: connection.rollback()
        cursor.close()
        connection.close()
        return jsonify({"status": "error", "message": str(error)}), 500

@app.route('/api/foods', methods=['GET'])
def get_foods():
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT food_id, food_name, calories_per_100g, protein_per_100g FROM food_items ORDER BY food_name;")
    rows = cursor.fetchall()
    cursor.close()
    connection.close()

    foods = []
    for row in rows:
        foods.append({
            "food_id": row[0],
            "name": row[1],
            "calories": float(row[2]),
            "protein": float(row[3])
        })
    return jsonify(foods)

@app.route('/api/foods', methods=['POST'])
def add_food():
    data = request.json
    food_name = data.get('food_name')
    calories = data.get('calories')
    protein = data.get('protein')

    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "INSERT INTO food_items (food_name, calories_per_100g, protein_per_100g) VALUES (%s, %s, %s);",
            (food_name, calories, protein)
        )
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": "Food item added successfully!"}), 201
    except Exception as error:
        if connection: connection.rollback()
        cursor.close()
        connection.close()
        return jsonify({"status": "error", "message": str(error)}), 500

@app.route('/api/log_meal', methods=['POST'])
def api_log_meal():
    data = request.json
    user_id = data.get('user_id')
    log_date = data.get('log_date')
    food_id = data.get('food_id')
    qty_grams = data.get('qty_grams')

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT current_weight FROM user_profile WHERE user_id = %s;", (user_id,))
        prof = cursor.fetchone()
        current_weight = prof[0] if prof else 75.0

        cursor.execute("INSERT INTO daily_logs (user_id, log_date, body_weight) VALUES (%s, %s, %s) RETURNING log_id;", (user_id, log_date, current_weight))
        log_id = cursor.fetchone()[0]

        cursor.execute("INSERT INTO meals (log_id, food_id, qty_grams) VALUES (%s, %s, %s);", (log_id, food_id, qty_grams))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": "Meal logged successfully!"}), 201
    except Exception as error:
        if connection: connection.rollback()
        cursor.close()
        connection.close()
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(error)}), 500

@app.route('/api/log_workout', methods=['POST'])
def api_log_workout():
    data = request.json
    user_id = data.get('user_id')
    log_date = data.get('log_date')
    exercise_name = data.get('exercise_name')
    sets = data.get('sets', 3)
    reps = data.get('reps', 10)
    weight_kg = data.get('weight_kg', 50)
    calories_burned = data.get('calories_burned', 150)

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT current_weight FROM user_profile WHERE user_id = %s;", (user_id,))
        prof = cursor.fetchone()
        current_weight = prof[0] if prof else 75.0

        cursor.execute("INSERT INTO daily_logs (user_id, log_date, body_weight) VALUES (%s, %s, %s) RETURNING log_id;", (user_id, log_date, current_weight))
        log_id = cursor.fetchone()[0]

        cursor.execute("INSERT INTO workout_logs (log_id, exercise_name, sets, reps, weight_kg, calories_burned) VALUES (%s, %s, %s, %s, %s, %s);",
                       (log_id, exercise_name, sets, reps, weight_kg, calories_burned))
        
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": f"{exercise_name} logged successfully!"}), 201
    except Exception as error:
        if connection: connection.rollback()
        cursor.close()
        connection.close()
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(error)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
