import io
import os
import sqlite3
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    REPORTLAB_AVAILABLE = True
except ImportError:
    A4 = (595.27, 841.89)
    ImageReader = None
    pdf_canvas = None
    REPORTLAB_AVAILABLE = False

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

st.set_page_config(page_title="Rwang'ondu School Dashboard", layout="wide")


def init_db() -> None:
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
        conn.commit()


def seed_initial_roster_if_empty() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        if count > 0:
            return

        sample_students = [
            ("RWG-701", "Faith Wanjiku", "Grade 7", "A", "+254712000701"),
            ("RWG-702", "Brian Mwangi", "Grade 7", "A", "+254712000702"),
            ("RWG-703", "Mercy Otieno", "Grade 7", "B", "+254712000703"),
            ("RWG-704", "Kevin Kamau", "Grade 7", "C", "+254712000704"),
            ("RWG-801", "Sharon Njeri", "Grade 8", "A", "+254712000801"),
            ("RWG-802", "Dennis Ochieng", "Grade 8", "B", "+254712000802"),
            ("RWG-803", "Purity Wambui", "Grade 8", "C", "+254712000803"),
            ("RWG-901", "Ian Kiprop", "Grade 9", "A", "+254712000901"),
            ("RWG-902", "Esther Muthoni", "Grade 9", "A", "+254712000902"),
            ("RWG-903", "Collins Njoroge", "Grade 9", "B", "+254712000903"),
            ("RWG-904", "Naomi Mutua", "Grade 9", "C", "+254712000904"),
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO students (admission_no, student_name, grade, stream, parent_whatsapp)
            VALUES (?, ?, ?, ?, ?)
            """,
            sample_students,
        )
        conn.commit()


@st.cache_data
def load_students_data(refresh_token: int = 0) -> pd.DataFrame:
    _ = refresh_token
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query("SELECT * FROM students ORDER BY grade, stream, admission_no", conn)


@st.cache_data
def load_marks_data(refresh_token: int = 0) -> pd.DataFrame:
    _ = refresh_token
    with sqlite3.connect(DB_PATH) as conn:
        query = """
            SELECT
                m.id,
                m.term,
                m.exam,
                s.grade,
                s.stream,
                m.admission_no,
                s.student_name,
                s.parent_whatsapp,
                m.subject,
                m.score
            FROM marks m
            JOIN students s ON m.admission_no = s.admission_no
        """
        return pd.read_sql_query(query, conn)


def upsert_students(rows: List[tuple]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
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
            rows,
        )
        conn.commit()


def upsert_marks(rows: List[tuple]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            """
            INSERT INTO marks (term, exam, grade, stream, admission_no, subject, score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(term, exam, admission_no, subject)
            DO UPDATE SET
                grade = excluded.grade,
                stream = excluded.stream,
                score = excluded.score
            """,
            rows,
        )
        conn.commit()


def recommend_pathway(avg_score: float, sci_score: float, pretech_score: float, arts_hum_avg: float) -> str:
    if avg_score >= 70 and max(sci_score, pretech_score) >= 65:
        if pretech_score >= sci_score + 5:
            return "STEM — Technical & Engineering"
        return "STEM — Pure & Applied Sciences"
    if arts_hum_avg >= avg_score and avg_score >= 55:
        return "Social Sciences & Humanities"
    if pretech_score >= 60 or avg_score >= 50:
        return "Arts & Sports Science"
    return "Foundation & Remedial Support"


def build_student_chart(student_df: pd.DataFrame) -> bytes:
    subj_scores = student_df.groupby("subject", as_index=False)["score"].mean()
    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=200)
    ax.barh(subj_scores["subject"], subj_scores["score"], color="#1F4E79")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Score (%)")
    ax.set_title("Learner Subject Breakdown (9 Subjects)")
    ax.invert_yaxis()
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_pdf_report(
    student_name: str,
    admission_no: str,
    grade: str,
    stream: str,
    term: str,
    exam_label: str,
    pathway: str,
    student_df: pd.DataFrame,
    chart_bytes: bytes,
) -> bytes:
    if not REPORTLAB_AVAILABLE or pdf_canvas is None or ImageReader is None:
        raise RuntimeError("Install reportlab (`pip install reportlab`) to generate PDF reports.")

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    _, height = A4

    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, height - 50, "Rwang'ondu School — Academic Progress & Pathway Report")

    c.setFont("Helvetica", 10.5)
    c.drawString(40, height - 72, f"Learner: {student_name} ({admission_no}) | {grade} {stream} | {term} ({exam_label})")

    avg_score = float(student_df["score"].mean())
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(40, height - 92, f"Mean Score: {avg_score:.1f}%")
    if grade == "Grade 9":
        c.drawString(40, height - 108, f"Recommended Senior Pathway: {pathway}")

    subj_summary = student_df.groupby("subject", as_index=False)["score"].mean()
    y = height - 138
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Subject (9 Junior School Areas)")
    c.drawString(300, y, "Score (%)")
    y -= 16

    c.setFont("Helvetica", 9.5)
    for _, row in subj_summary.iterrows():
        c.drawString(40, y, str(row["subject"]))
        c.drawString(300, y, f"{float(row['score']):.1f}")
        y -= 14

    chart_top = min(y - 10, 360)
    chart_height = max(135, min(210, chart_top - 65))
    chart_img = ImageReader(io.BytesIO(chart_bytes))
    c.drawImage(chart_img, 40, chart_top - chart_height, width=500, height=chart_height, preserveAspectRatio=True)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def send_whatsapp_placeholder(phone: str, message: str, pdf_path: Optional[str] = None) -> str:
    pdf_info = f" (PDF: {pdf_path})" if pdf_path else ""
    return f"Queued WhatsApp update to {phone}{pdf_info}: {message}"


def read_uploaded_table(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


init_db()
seed_initial_roster_if_empty()
if "db_version" not in st.session_state:
    st.session_state.db_version = 0

students_df = load_students_data(st.session_state.db_version)
df = load_marks_data(st.session_state.db_version)

st.title("Academic & Pathway Dashboard")
st.caption("Rwang'ondu School — Grades 7 to 9 (Streams A, B & C) • 9 Subjects • Opener to End-Term")

# Sidebar filters
terms_opt = ["All terms"] + TERMS
selected_term = st.sidebar.selectbox("Term", terms_opt)

exams_opt = ["All exams"] + EXAMS
selected_exam = st.sidebar.selectbox("Exam", exams_opt)

grades_opt = ["All grades"] + GRADES
selected_grade = st.sidebar.selectbox("Grade", grades_opt)

streams_opt = ["All streams"] + STREAMS
selected_stream = st.sidebar.selectbox("Stream", streams_opt)

filtered = df.copy()
if not filtered.empty:
    if selected_term != "All terms":
        filtered = filtered[filtered["term"] == selected_term]
    if selected_exam != "All exams":
        filtered = filtered[filtered["exam"] == selected_exam]
    if selected_grade != "All grades":
        filtered = filtered[filtered["grade"] == selected_grade]
    if selected_stream != "All streams":
        filtered = filtered[filtered["stream"] == selected_stream]

# KPI row
k1, k2, k3 = st.columns(3)
k1.metric("Mean Score", f"{filtered['score'].mean():.1f}%" if not filtered.empty else "0.0%")
k2.metric("Learners in Roster", int(students_df["admission_no"].nunique()) if not students_df.empty else 0)
k3.metric(
    "Top Subject",
    str(filtered.groupby("subject")["score"].mean().idxmax()) if not filtered.empty else "N/A",
)

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "Dashboard & Grade 9 Pathways",
        "Teacher Marks Entry",
        "Roster & Bulk Upload",
        "PDF Report & WhatsApp",
    ]
)

with tab1:
    if filtered.empty:
        st.info("No marks match the selected filters. Enter or bulk-upload marks to see analysis.")
    else:
        c1, c2 = st.columns(2)

        with c1:
            fig1, ax1 = plt.subplots(figsize=(6.5, 3.8), dpi=200)
            active_grades = [g for g in GRADES if g in filtered["grade"].unique()]
            gs_pivot = (
                filtered.groupby(["grade", "stream"])["score"]
                .mean()
                .unstack("stream")
                .reindex(index=active_grades, columns=STREAMS)
            )
            gs_pivot.plot(kind="bar", ax=ax1, color=["#1F4E79", "#2E86C1", "#85C1E9"])
            ax1.set_title("Mean Score by Grade & Stream")
            ax1.set_ylabel("Mean Score (%)")
            ax1.set_xlabel("")
            ax1.set_ylim(0, 100)
            plt.xticks(rotation=0)
            plt.tight_layout()
            st.pyplot(fig1)
            plt.close(fig1)

        with c2:
            fig2, ax2 = plt.subplots(figsize=(6.5, 3.8), dpi=200)
            subj_avg = filtered.groupby("subject")["score"].mean().sort_values(ascending=True)
            subj_avg.plot(kind="barh", ax=ax2, color="#2E86C1")
            ax2.set_title("Subject Performance (9 Subjects)")
            ax2.set_xlabel("Mean Score (%)")
            ax2.set_ylabel("")
            ax2.set_xlim(0, 100)
            plt.tight_layout()
            st.pyplot(fig2)
            plt.close(fig2)

        g9_df = filtered[filtered["grade"] == "Grade 9"]
        pathway_rows: List[dict] = []
        for (adm, sname, stream_val, term_val, exam_val), sdf in g9_df.groupby(
            ["admission_no", "student_name", "stream", "term", "exam"]
        ):
            subj_means = sdf.groupby("subject")["score"].mean().to_dict()
            avg_sc = float(sdf["score"].mean())
            sci_sc = float(subj_means.get("Integrated Science", avg_sc))
            pre_sc = float(subj_means.get("Pre-Technical Studies", avg_sc))
            hum_arts_avg = float(
                pd.Series(
                    [
                        v
                        for k, v in subj_means.items()
                        if k in ("English", "Kiswahili", "Social Studies", "Creative Arts & Sports", "Religious Education")
                    ]
                ).mean()
            )
            pathway = recommend_pathway(
                avg_sc,
                sci_sc,
                pre_sc,
                hum_arts_avg if pd.notna(hum_arts_avg) else avg_sc,
            )
            pathway_rows.append(
                {
                    "Term": term_val,
                    "Exam": exam_val,
                    "Admission No.": adm,
                    "Learner": sname,
                    "Stream": stream_val,
                    "Mean (%)": round(avg_sc, 1),
                    "Suggested Pathway": pathway,
                }
            )

        fig3, ax3 = plt.subplots(figsize=(10, 3.3), dpi=200)
        if pathway_rows:
            pdf_pathways = pd.DataFrame(pathway_rows)
            pdf_pathways["Suggested Pathway"].value_counts().sort_values(ascending=True).plot(
                kind="barh", ax=ax3, color="#1F4E79"
            )
            ax3.set_title("Grade 9 Recommended Pathways")
            ax3.set_xlabel("Number of Learners")
            ax3.set_ylabel("")
            plt.tight_layout()
            st.pyplot(fig3)
            plt.close(fig3)
            st.dataframe(pdf_pathways, use_container_width=True)
        else:
            plt.close(fig3)
            st.info("No Grade 9 marks in the current filter view.")

with tab2:
    st.subheader("Direct Mark Entry (Pre-Loaded Learner Roster)")
    e1, e2, e3, e4 = st.columns(4)
    entry_term = e1.selectbox("Term", TERMS, key="entry_term")
    entry_exam = e2.selectbox("Exam", EXAMS, key="entry_exam")
    entry_grade = e3.selectbox("Grade", GRADES, key="entry_grade")
    entry_stream = e4.selectbox("Stream", STREAMS, key="entry_stream")

    class_roster = students_df[
        (students_df["grade"] == entry_grade) & (students_df["stream"] == entry_stream)
    ]

    if class_roster.empty:
        st.warning(f"No learners in roster for {entry_grade} {entry_stream}. Add or bulk-upload them in 'Roster & Bulk Upload'.")
    else:
        learner_labels = [
            f"{r.admission_no} — {r.student_name} ({r.parent_whatsapp})"
            for r in class_roster.itertuples()
        ]
        selected_idx = st.selectbox("Select Learner (Already in System)", range(len(learner_labels)), format_func=lambda i: learner_labels[i])
        chosen_student = class_roster.iloc[selected_idx]

        with st.form("school_marks_form"):
            st.markdown(
                f"**Learner:** {chosen_student['student_name']} | **Adm No:** `{chosen_student['admission_no']}` | **Parent WhatsApp:** `{chosen_student['parent_whatsapp']}`"
            )
            marks_input: Dict[str, float] = {}
            cols = st.columns(3)
            for i, subj in enumerate(SUBJECTS):
                with cols[i % 3]:
                    marks_input[subj] = float(
                        st.number_input(subj, min_value=0.0, max_value=100.0, value=55.0, step=1.0, key=f"m_{subj}")
                    )

            if st.form_submit_button("Save Exam Marks"):
                mark_rows = [
                    (
                        entry_term,
                        entry_exam,
                        str(chosen_student["grade"]),
                        str(chosen_student["stream"]),
                        str(chosen_student["admission_no"]),
                        subj,
                        sc,
                    )
                    for subj, sc in marks_input.items()
                ]
                upsert_marks(mark_rows)
                st.session_state.db_version += 1
                st.success(
                    f"Saved {entry_exam} ({entry_term}) marks for {chosen_student['student_name']} ({chosen_student['admission_no']})."
                )
                st.rerun()

with tab3:
    st.subheader("Learner Roster & Bulk CSV / Excel Upload")
    st.dataframe(students_df, use_container_width=True)

    st.markdown("### 1. Add Single Learner to System")
    with st.form("add_student_form"):
        a1, a2, a3, a4, a5 = st.columns(5)
        new_adm = a1.text_input("Admission No.", placeholder="RWG-905")
        new_name = a2.text_input("Full Name", placeholder="Grace Akinyi")
        new_grade = a3.selectbox("Grade", GRADES, key="new_grade")
        new_stream = a4.selectbox("Stream", STREAMS, key="new_stream")
        new_wa = a5.text_input("Parent WhatsApp", placeholder="+2547XXXXXXXX")

        if st.form_submit_button("Save Learner to Roster"):
            if not new_adm.strip() or not new_name.strip() or not new_wa.strip():
                st.error("Admission No., Full Name, and Parent WhatsApp are required.")
            else:
                upsert_students(
                    [(new_adm.strip(), new_name.strip(), new_grade, new_stream, new_wa.strip())]
                )
                st.session_state.db_version += 1
                st.success(f"Saved {new_name.strip()} ({new_adm.strip()}) to roster.")
                st.rerun()

    st.markdown("### 2. Bulk Upload Learners (CSV or Excel)")
    st.caption("Required columns: `admission_no`, `student_name`, `grade`, `stream`, `parent_whatsapp`")
    roster_template = pd.DataFrame(
        [
            {
                "admission_no": "RWG-910",
                "student_name": "Daniel Kipkoech",
                "grade": "Grade 9",
                "stream": "A",
                "parent_whatsapp": "+254712000910",
            }
        ]
    )
    st.download_button(
        "Download Learner Roster CSV Template",
        data=roster_template.to_csv(index=False).encode("utf-8"),
        file_name="rwangondu_roster_template.csv",
        mime="text/csv",
    )
    roster_upload = st.file_uploader("Upload Learner Roster (.csv or .xlsx)", type=["csv", "xlsx"], key="roster_up")
    if roster_upload is not None and st.button("Import Learner Roster"):
        try:
            up_df = read_uploaded_table(roster_upload)
            req_cols = {"admission_no", "student_name", "grade", "stream", "parent_whatsapp"}
            if not req_cols.issubset(set(up_df.columns)):
                st.error(f"Missing columns. Expected: {sorted(req_cols)}")
            else:
                s_rows = [
                    (
                        str(r["admission_no"]).strip(),
                        str(r["student_name"]).strip(),
                        str(r["grade"]).strip(),
                        str(r["stream"]).strip(),
                        str(r["parent_whatsapp"]).strip(),
                    )
                    for _, r in up_df.iterrows()
                ]
                upsert_students(s_rows)
                st.session_state.db_version += 1
                st.success(f"Imported {len(s_rows)} learners into roster.")
                st.rerun()
        except Exception as err:
            st.error(f"Failed to import roster: {err}")

    st.markdown("### 3. Bulk Upload Exam Marks (Long or Wide Format — CSV or Excel)")
    st.caption(
        "Supports **Long format** (`term`, `exam`, `admission_no`, `subject`, `score`) OR "
        "**Wide format** (`term`, `exam`, `admission_no`, plus any of the 9 subject columns)."
    )
    marks_template = pd.DataFrame(
        [
            {
                "term": "Term 1",
                "exam": "Mid-Term",
                "admission_no": "RWG-901",
                "Mathematics": 68,
                "English": 72,
                "Kiswahili": 65,
                "Integrated Science": 74,
                "Social Studies": 69,
                "Pre-Technical Studies": 71,
                "Agriculture": 66,
                "Creative Arts & Sports": 70,
                "Religious Education": 75,
            }
        ]
    )
    st.download_button(
        "Download Bulk Marks CSV Template",
        data=marks_template.to_csv(index=False).encode("utf-8"),
        file_name="rwangondu_marks_template.csv",
        mime="text/csv",
    )
    marks_upload = st.file_uploader("Upload Marks File (.csv or .xlsx)", type=["csv", "xlsx"], key="marks_up")
    if marks_upload is not None and st.button("Import Bulk Marks"):
        try:
            mdf = read_uploaded_table(marks_upload)
            student_lookup = students_df.set_index("admission_no")[["grade", "stream"]].to_dict("index")
            mark_rows: List[tuple] = []

            if {"term", "exam", "admission_no", "subject", "score"}.issubset(set(mdf.columns)):
                for _, r in mdf.iterrows():
                    adm = str(r["admission_no"]).strip()
                    if adm not in student_lookup:
                        continue
                    mark_rows.append(
                        (
                            str(r["term"]).strip(),
                            str(r["exam"]).strip(),
                            str(student_lookup[adm]["grade"]),
                            str(student_lookup[adm]["stream"]),
                            adm,
                            str(r["subject"]).strip(),
                            float(r["score"]),
                        )
                    )
            else:
                subj_cols = [c for c in SUBJECTS if c in mdf.columns]
                if not {"term", "exam", "admission_no"}.issubset(set(mdf.columns)) or not subj_cols:
                    st.error("Provide `term`, `exam`, `admission_no`, and either `subject`+`score` or subject columns.")
                else:
                    for _, r in mdf.iterrows():
                        adm = str(r["admission_no"]).strip()
                        if adm not in student_lookup:
                            continue
                        for sc_name in subj_cols:
                            if pd.notna(r[sc_name]):
                                mark_rows.append(
                                    (
                                        str(r["term"]).strip(),
                                        str(r["exam"]).strip(),
                                        str(student_lookup[adm]["grade"]),
                                        str(student_lookup[adm]["stream"]),
                                        adm,
                                        sc_name,
                                        float(r[sc_name]),
                                    )
                                )

            if mark_rows:
                upsert_marks(mark_rows)
                st.session_state.db_version += 1
                st.success(f"Imported {len(mark_rows)} subject mark entries.")
                st.rerun()
            else:
                st.warning("No matching learner admission numbers found in the roster for those marks.")
        except Exception as err:
            st.error(f"Failed to import marks: {err}")

with tab4:
    st.subheader("PDF Report & Parent WhatsApp")
    if df.empty:
        st.info("Enter or bulk-upload learner marks first to generate reports.")
    else:
        roster_marks = df[["admission_no", "student_name", "grade", "stream", "term", "parent_whatsapp"]].drop_duplicates()
        options = [
            f"{r.admission_no} — {r.student_name} ({r.grade} {r.stream}, {r.term})"
            for r in roster_marks.itertuples()
        ]
        chosen = st.selectbox("Select Learner & Term", range(len(options)), format_func=lambda i: options[i])
        row = roster_marks.iloc[chosen]

        exam_choices = ["All Exams (Term Average)"] + sorted(
            df[(df["admission_no"] == row["admission_no"]) & (df["term"] == row["term"])]["exam"].unique().tolist()
        )
        chosen_exam = st.selectbox("Report Exam Scope", exam_choices)

        sdf = df[(df["admission_no"] == row["admission_no"]) & (df["term"] == row["term"])]
        if chosen_exam != "All Exams (Term Average)":
            sdf = sdf[sdf["exam"] == chosen_exam]

        subj_means = sdf.groupby("subject")["score"].mean().to_dict()
        avg_sc = float(sdf["score"].mean())
        hum_arts_avg = float(
            pd.Series(
                [
                    v
                    for k, v in subj_means.items()
                    if k in ("English", "Kiswahili", "Social Studies", "Creative Arts & Sports", "Religious Education")
                ]
            ).mean()
        )
        pathway = recommend_pathway(
            avg_sc,
            float(subj_means.get("Integrated Science", avg_sc)),
            float(subj_means.get("Pre-Technical Studies", avg_sc)),
            hum_arts_avg if pd.notna(hum_arts_avg) else avg_sc,
        )

        chart_png = build_student_chart(sdf)
        st.image(chart_png, caption=f"{row['student_name']} — {row['term']} ({chosen_exam})")

        os.makedirs("term_reports", exist_ok=True)
        safe_scope = chosen_exam.replace(" ", "_").replace("(", "").replace(")", "")
        pdf_file = os.path.join("term_reports", f"{row['admission_no']}_{str(row['term']).replace(' ', '_')}_{safe_scope}.pdf")

        if st.button("Generate PDF Report"):
            try:
                pdf_data = generate_pdf_report(
                    student_name=str(row["student_name"]),
                    admission_no=str(row["admission_no"]),
                    grade=str(row["grade"]),
                    stream=str(row["stream"]),
                    term=str(row["term"]),
                    exam_label=chosen_exam,
                    pathway=pathway,
                    student_df=sdf,
                    chart_bytes=chart_png,
                )
                with open(pdf_file, "wb") as f:
                    f.write(pdf_data)
                st.download_button(
                    "Download PDF",
                    data=pdf_data,
                    file_name=os.path.basename(pdf_file),
                    mime="application/pdf",
                )
                st.success(f"Saved {pdf_file}")
            except Exception as err:
                st.error(str(err))

        wa_text = (
            f"Rwang'ondu School ({row['term']} - {chosen_exam}): {row['student_name']} ({row['grade']} {row['stream']}) "
            f"mean score is {avg_sc:.1f}%."
            + (f" Recommended pathway: {pathway}." if row["grade"] == "Grade 9" else "")
        )
        st.text_area("Parent WhatsApp Message", value=wa_text, height=85)
        if st.button("Send via WhatsApp"):
            st.info(
                send_whatsapp_placeholder(
                    str(row["parent_whatsapp"]),
                    wa_text,
                    pdf_file if os.path.exists(pdf_file) else None,
                )
            )