import sqlite3
import numpy as np

DB_PATH = "rwangondu_school.db"
TERMS = ["Term 1", "Term 2", "Term 3"]
EXAMS = ["Opener", "Mid-Term", "End-Month", "End-Term"]
GRADES = ["Grade 7", "Grade 8", "Grade 9"]
STREAMS = ["A", "B", "C"]
SUBJECTS = [
    "Mathematics",
    "English",
    "Kiswahili",
    "Integrated Science",
    "Social Studies",
    "Pre-Technical Studies",
    "Agriculture",
    "Creative Arts & Sports",
    "Religious Education",
]

FIRST_NAMES = [
    "Brian", "Faith", "Kevin", "Mercy", "Dennis", "Sharon",
    "Ian", "Purity", "Victor", "Esther", "Collins", "Naomi",
]
LAST_NAMES = [
    "Mwangi", "Wanjiku", "Kamau", "Otieno", "Ochieng", "Mutua",
    "Kiprop", "Njeri", "Wambui", "Kariuki", "Muthoni", "Njoroge",
]


def seed_full_dummy_data(learners_per_stream: int = 5) -> None:
    rng = np.random.default_rng(101)
    stream_boost = {"A": 7.5, "B": 1.5, "C": -3.5}
    exam_boost = {"Opener": -2.5, "Mid-Term": -0.5, "End-Month": 1.0, "End-Term": 2.5}
    term_boost = {"Term 1": -1.5, "Term 2": 0.5, "Term 3": 2.0}

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                admission_no TEXT PRIMARY KEY,
                student_name TEXT NOT NULL,
                grade TEXT NOT NULL,
                stream TEXT NOT NULL,
                parent_whatsapp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term TEXT NOT NULL,
                exam TEXT NOT NULL,
                grade TEXT NOT NULL,
                stream TEXT NOT NULL,
                admission_no TEXT NOT NULL,
                subject TEXT NOT NULL,
                score REAL NOT NULL,
                UNIQUE(term, exam, admission_no, subject),
                FOREIGN KEY (admission_no) REFERENCES students(admission_no)
            )
            """
        )

        adm_num = 101
        total_learners = 0

        for grade in GRADES:
            for stream in STREAMS:
                for _ in range(learners_per_stream):
                    adm_no = f"RWG-{adm_num}"
                    adm_num += 1
                    total_learners += 1
                    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
                    phone = f"+2547{int(rng.integers(10000000, 99999999))}"
                    baseline = float(rng.normal(61.0, 10.5))

                    conn.execute(
                        """
                        INSERT INTO students (admission_no, student_name, grade, stream, parent_whatsapp)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(admission_no)
                        DO UPDATE SET
                            student_name = excluded.student_name,
                            grade = excluded.grade,
                            stream = excluded.stream,
                            parent_whatsapp = excluded.parent_whatsapp
                        """,
                        (adm_no, name, grade, stream, phone),
                    )

                    for term in TERMS:
                        for exam in EXAMS:
                            for subj in SUBJECTS:
                                subj_shift = 2.5 if (subj == "Pre-Technical Studies" and stream == "A") else 0.0
                                raw = (
                                    baseline
                                    + stream_boost[stream]
                                    + term_boost[term]
                                    + exam_boost[exam]
                                    + subj_shift
                                    + float(rng.normal(0, 6.5))
                                )
                                score = round(float(np.clip(raw, 28.0, 97.0)), 1)

                                conn.execute(
                                    """
                                    INSERT INTO marks (term, exam, grade, stream, admission_no, subject, score)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                    ON CONFLICT(term, exam, admission_no, subject)
                                    DO UPDATE SET
                                        grade = excluded.grade,
                                        stream = excluded.stream,
                                        score = excluded.score
                                    """,
                                    (term, exam, grade, stream, adm_no, subj, score),
                                )

        conn.commit()
    print(f"Seeded {total_learners} learners across Grades 7–9 (Streams A, B, C) with 9 subjects and 4 exams.")


if __name__ == "__main__":
    seed_full_dummy_data(learners_per_stream=5)