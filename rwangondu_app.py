import io
import os
import sqlite3
import urllib.parse
import zipfile
from datetime import datetime
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
    A4, ImageReader, pdf_canvas, REPORTLAB_AVAILABLE = (595.27, 841.89), None, None, False

DB_PATH = "rwangondu_school.db"
TERMS = ["Term 1", "Term 2", "Term 3"]
EXAMS = ["Opener", "Mid-Term", "End-Month", "End-Term"]
GRADES = ["Grade 7", "Grade 8", "Grade 9"]
STREAMS = ["A", "B", "C"]
SUBJECTS = [
    "Mathematics", "English", "Kiswahili", "Integrated Science", "Social Studies",
    "Pre-Technical Studies", "Agriculture", "Creative Arts & Sports", "Religious Education",
]
HUM_ARTS_SUBJS = ("English", "Kiswahili", "Social Studies", "Creative Arts & Sports", "Religious Education")

st.set_page_config(page_title="Rwang'ondu School Dashboard", layout="wide")


def knec_grade(pct: float) -> tuple[str, int, str]:
    for cutoff, code, pts, label in [
        (90, "EE1", 8, "Exceptional"), (75, "EE2", 7, "Very Good"), (58, "ME1", 6, "Good"),
        (41, "ME2", 5, "Fair"), (31, "AE1", 4, "Needs Improvement"), (21, "AE2", 3, "Below Average"),
        (11, "BE1", 2, "Well Below Average"), (0, "BE2", 1, "Minimal"),
    ]:
        if pct >= cutoff:
            return code, pts, label
    return "BE2", 1, "Minimal"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS students (admission_no TEXT PRIMARY KEY, student_name TEXT NOT NULL, grade TEXT NOT NULL, stream TEXT NOT NULL, parent_whatsapp TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY AUTOINCREMENT, term TEXT NOT NULL, exam TEXT NOT NULL, grade TEXT NOT NULL, stream TEXT NOT NULL, admission_no TEXT NOT NULL, subject TEXT NOT NULL, score REAL NOT NULL, max_marks REAL NOT NULL DEFAULT 100.0, UNIQUE(term, exam, admission_no, subject), FOREIGN KEY (admission_no) REFERENCES students(admission_no))")
        conn.execute("CREATE TABLE IF NOT EXISTS upload_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, uploaded_at TEXT NOT NULL, upload_type TEXT NOT NULL, source_name TEXT NOT NULL, rows_imported INTEGER NOT NULL, preview_json TEXT NOT NULL)")
        if "max_marks" not in [r[1] for r in conn.execute("PRAGMA table_info(marks)").fetchall()]:
            conn.execute("ALTER TABLE marks ADD COLUMN max_marks REAL NOT NULL DEFAULT 100.0")
        if conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO students VALUES (?, ?, ?, ?, ?)",
                [
                    ("RWG-701", "Faith Wanjiku", "Grade 7", "A", "+254712000701"), ("RWG-702", "Brian Mwangi", "Grade 7", "A", "+254712000702"),
                    ("RWG-703", "Mercy Otieno", "Grade 7", "B", "+254712000703"), ("RWG-704", "Kevin Kamau", "Grade 7", "C", "+254712000704"),
                    ("RWG-801", "Sharon Njeri", "Grade 8", "A", "+254712000801"), ("RWG-802", "Dennis Ochieng", "Grade 8", "B", "+254712000802"),
                    ("RWG-803", "Purity Wambui", "Grade 8", "C", "+254712000803"), ("RWG-901", "Ian Kiprop", "Grade 9", "A", "+254712000901"),
                    ("RWG-902", "Esther Muthoni", "Grade 9", "A", "+254712000902"), ("RWG-903", "Collins Njoroge", "Grade 9", "B", "+254712000903"),
                    ("RWG-904", "Naomi Mutua", "Grade 9", "C", "+254712000904"),
                ],
            )
        conn.commit()


def log_upload(u_type: str, src_name: str, count: int, preview_df: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO upload_logs (uploaded_at, upload_type, source_name, rows_imported, preview_json) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), u_type, src_name, int(count), preview_df.head(50).to_json(orient="records") if not preview_df.empty else "[]"),
        )
        conn.commit()


@st.cache_data
def load_students(refresh_token: int = 0) -> pd.DataFrame:
    _ = refresh_token
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query("SELECT * FROM students ORDER BY grade, stream, admission_no", conn)


@st.cache_data
def load_marks(refresh_token: int = 0) -> pd.DataFrame:
    _ = refresh_token
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query("SELECT m.id, m.term, m.exam, s.grade, s.stream, m.admission_no, s.student_name, s.parent_whatsapp, m.subject, m.score, m.max_marks FROM marks m JOIN students s ON m.admission_no = s.admission_no", conn)


@st.cache_data
def load_logs(refresh_token: int = 0) -> pd.DataFrame:
    _ = refresh_token
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query("SELECT * FROM upload_logs ORDER BY id DESC", conn)


def upsert_students(rows: List[tuple]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany("INSERT INTO students (admission_no, student_name, grade, stream, parent_whatsapp) VALUES (?, ?, ?, ?, ?) ON CONFLICT(admission_no) DO UPDATE SET student_name=excluded.student_name, grade=excluded.grade, stream=excluded.stream, parent_whatsapp=excluded.parent_whatsapp", rows)
        conn.commit()


def upsert_marks(rows: List[tuple]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany("INSERT INTO marks (term, exam, grade, stream, admission_no, subject, score, max_marks) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(term, exam, admission_no, subject) DO UPDATE SET grade=excluded.grade, stream=excluded.stream, score=excluded.score, max_marks=excluded.max_marks", rows)
        conn.commit()


def enrich_marks(data: pd.DataFrame, to_pct: bool) -> pd.DataFrame:
    out = data.copy()
    if out.empty:
        out["display_score"] = []
        return out
    out["pct"] = (out["score"] / out["max_marks"].replace(0, 100.0)) * 100.0
    g_info = out["pct"].apply(knec_grade)
    out["knec_level"] = [g[0] for g in g_info]
    out["knec_pts"] = [g[1] for g in g_info]
    out["display_score"] = out["pct"] if to_pct else out["score"]
    return out


def recommend_pathway(avg_pct: float, sci_pct: float, pretech_pct: float, arts_hum_avg: float) -> str:
    if avg_pct >= 70 and max(sci_pct, pretech_pct) >= 65:
        return "STEM — Technical & Engineering" if pretech_pct >= sci_pct + 5 else "STEM — Pure & Applied Sciences"
    if arts_hum_avg >= avg_pct and avg_pct >= 55:
        return "Social Sciences & Humanities"
    return "Arts & Sports Science" if (pretech_pct >= 60 or avg_pct >= 50) else "Foundation & Remedial Support"


def make_chart(data_obj, title: str, xlabel: str, xlim_max: Optional[float] = None, kind: str = "barh", figsize=(6.5, 3.8)) -> bytes:
    fig, ax = plt.subplots(figsize=figsize, dpi=200)
    if kind == "bar_pivot":
        data_obj.plot(kind="bar", ax=ax, color=["#1F4E79", "#2E86C1", "#85C1E9"])
        plt.xticks(rotation=0)
    else:
        data_obj.plot(kind=kind, ax=ax, color="#2E86C1" if kind == "barh" else "#1F4E79")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("")
    if xlim_max is not None:
        (ax.set_ylim if kind == "bar_pivot" else ax.set_xlim)(0, xlim_max)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_pdf(student_name: str, admission_no: str, grade: str, stream: str, term: str, exam_label: str, pathway: str, unit_label: str, student_df: pd.DataFrame, chart_bytes: bytes) -> bytes:
    if not REPORTLAB_AVAILABLE or pdf_canvas is None or ImageReader is None:
        raise RuntimeError("Install reportlab (`pip install reportlab`) for PDF reports.")
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    _, h = A4
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "Rwang'ondu School — Academic & KNEC Level Report")
    c.setFont("Helvetica", 10)
    c.drawString(40, h - 70, f"Learner: {student_name} ({admission_no}) | {grade} {stream} | {term} ({exam_label})")
    lvl, pts, _ = knec_grade(float(student_df["pct"].mean()))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, h - 90, f"Mean: {float(student_df['display_score'].mean()):.1f} {unit_label} | KNEC Band: {lvl} ({pts} pts)")
    if grade == "Grade 9":
        c.drawString(40, h - 106, f"Recommended Senior Pathway: {pathway}")

    y = h - 134
    c.setFont("Helvetica-Bold", 9.5)
    for x_pos, col_txt in [(40, "Subject"), (230, "Raw/Max"), (310, f"Score ({unit_label})"), (410, "KNEC Level")]:
        c.drawString(x_pos, y, col_txt)
    y -= 15
    c.setFont("Helvetica", 9)
    for _, r in student_df.groupby("subject", as_index=False)[["score", "max_marks", "display_score", "pct"]].mean().iterrows():
        s_lvl, s_pts, _ = knec_grade(float(r["pct"]))
        for x_pos, val_txt in [(40, str(r["subject"])), (230, f"{float(r['score']):.1f}/{float(r['max_marks']):.0f}"), (310, f"{float(r['display_score']):.1f} {unit_label}"), (410, f"{s_lvl} ({s_pts}pt)")]:
            c.drawString(x_pos, y, val_txt)
        y -= 14

    chart_top = min(y - 10, 355)
    chart_h = max(130, min(200, chart_top - 65))
    c.drawImage(ImageReader(io.BytesIO(chart_bytes)), 40, chart_top - chart_h, width=500, height=chart_h, preserveAspectRatio=True)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def parse_bulk_marks(mdf: pd.DataFrame, lookup: dict, default_max: float) -> List[tuple]:
    rows: List[tuple] = []
    has_long = {"term", "exam", "admission_no", "subject", "score"}.issubset(mdf.columns)
    subj_cols = [c for c in SUBJECTS if c in mdf.columns]
    if not has_long and not ({"term", "exam", "admission_no"}.issubset(mdf.columns) and subj_cols):
        raise ValueError("Provide term, exam, admission_no, and subject+score or subject columns.")
    for _, r in mdf.iterrows():
        adm = str(r["admission_no"]).strip()
        if adm not in lookup:
            continue
        mm = float(r["max_marks"]) if "max_marks" in mdf.columns and pd.notna(r["max_marks"]) else default_max
        g, s, t, ex = str(lookup[adm]["grade"]), str(lookup[adm]["stream"]), str(r["term"]).strip(), str(r["exam"]).strip()
        if has_long:
            rows.append((t, ex, g, s, adm, str(r["subject"]).strip(), float(r["score"]), mm))
        else:
            for sc_name in subj_cols:
                if pd.notna(r[sc_name]):
                    rows.append((t, ex, g, s, adm, sc_name, float(r[sc_name]), mm))
    return rows


def build_rankings(data: pd.DataFrame, unit_label: str) -> pd.DataFrame:
    col_m = f"Mean ({unit_label})"
    if data.empty:
        return pd.DataFrame(columns=["Rank", "Grade", "Stream", "Learners", col_m, "KNEC Band"])
    ranked = data.groupby(["grade", "stream"], as_index=False).agg(Learners=("admission_no", "nunique"), Mean_Val=("display_score", "mean"), Mean_Pct=("pct", "mean")).sort_values(by=["Mean_Val", "Learners"], ascending=[False, False]).reset_index(drop=True)
    ranked.insert(0, "Rank", [f"#{i + 1}" for i in range(len(ranked))])
    ranked[col_m] = ranked["Mean_Val"].round(1)
    ranked["KNEC Band"] = [f"{knec_grade(p)[0]} ({knec_grade(p)[1]}pt)" for p in ranked["Mean_Pct"]]
    return ranked[["Rank", "grade", "stream", "Learners", col_m, "KNEC Band"]].rename(columns={"grade": "Grade", "stream": "Stream"})


def build_results_table(data: pd.DataFrame, unit_label: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    idx_cols = ["admission_no", "student_name", "grade", "stream", "term", "exam"]
    piv = data.pivot_table(index=idx_cols, columns="subject", values="display_score", aggfunc="mean").reset_index()
    present = [c for c in SUBJECTS if c in piv.columns]
    if present:
        col_m = f"Mean ({unit_label})"
        piv[col_m] = piv[present].mean(axis=1).round(1)
        piv_idx = piv.set_index(idx_cols).index
        pts_map = data.groupby(idx_cols + ["subject"])["knec_pts"].first().unstack("subject")
        pts_cols = [c for c in SUBJECTS if c in pts_map.columns]
        if pts_cols:
            piv["Total KNEC Pts"] = pts_map[pts_cols].sum(axis=1).reindex(piv_idx).fillna(0).astype(int).values
        avg_pct_s = data.groupby(idx_cols)["pct"].mean().reindex(piv_idx).fillna(0)
        piv["KNEC Level"] = [knec_grade(float(v))[0] for v in avg_pct_s.values]
        piv["Grade Rank"] = piv.groupby(["grade", "term", "exam"])[col_m].rank(ascending=False, method="min").astype(int)
        piv["Stream Rank"] = piv.groupby(["grade", "stream", "term", "exam"])[col_m].rank(ascending=False, method="min").astype(int)
        piv = piv.sort_values(by=["grade", "term", "exam", "Grade Rank", col_m], ascending=[True, True, True, True, False])
        front = ["Grade Rank", "Stream Rank", "admission_no", "student_name", "grade", "stream"]
        piv = piv[front + [c for c in piv.columns if c not in front]]
    return piv


def read_file(up) -> pd.DataFrame:
    return pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)


init_db()
st.session_state.setdefault("db_version", 0)
students_df = load_students(st.session_state.db_version)
raw_df = load_marks(st.session_state.db_version)
logs_df = load_logs(st.session_state.db_version)

st.title("Academic & Pathway Dashboard")
st.caption("Rwang'ondu School — Grades 7–9 (Streams A, B, C) • 9 Subjects • KNEC Levels • Flexible Max Marks")

selected_term = st.sidebar.selectbox("Term", ["All terms"] + TERMS)
selected_exam = st.sidebar.selectbox("Exam", ["All exams"] + EXAMS)
selected_grade = st.sidebar.selectbox("Grade", ["All grades"] + GRADES)
selected_stream = st.sidebar.selectbox("Stream", ["All streams"] + STREAMS)
convert_to_pct = st.sidebar.checkbox("Convert scores to percentage (%)", value=False)
unit_label = "%" if convert_to_pct else "Marks"
df = enrich_marks(raw_df, convert_to_pct)


def apply_filters(frame: pd.DataFrame, include_stream: bool = True) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    for col, val in [("term", selected_term), ("exam", selected_exam), ("grade", selected_grade)] + ([("stream", selected_stream)] if include_stream else []):
        if not val.startswith("All "):
            out = out[out[col] == val]
    return out


filtered = apply_filters(df, include_stream=True)
k1, k2, k3 = st.columns(3)
k1.metric(f"Mean Score ({unit_label})", f"{filtered['display_score'].mean():.1f}" if not filtered.empty else "0.0")
k2.metric("Learners in Roster", int(students_df["admission_no"].nunique()))
k3.metric("Top Subject", str(filtered.groupby("subject")["display_score"].mean().idxmax()) if not filtered.empty else "N/A")

tab1, tab2, tab3, tab4 = st.tabs(["Dashboard, Rankings & Backend", "Teacher Marks Entry", "Roster & Bulk Upload", "PDF Report & Messaging"])

with tab1:
    if filtered.empty:
        st.info("No marks match the current filters.")
    else:
        c1, c2 = st.columns(2)
        xlim_val = 100.0 if convert_to_pct else None
        active_g = [g for g in GRADES if g in filtered["grade"].unique()]
        gs_piv = filtered.groupby(["grade", "stream"])["display_score"].mean().unstack("stream").reindex(index=active_g, columns=STREAMS)
        c1.image(make_chart(gs_piv, f"Mean ({unit_label}) by Grade & Stream", f"Mean ({unit_label})", xlim_val, "bar_pivot"))
        c2.image(make_chart(filtered.groupby("subject")["display_score"].mean().sort_values(), f"Subject Performance ({unit_label})", f"Mean ({unit_label})", xlim_val, "barh"))

        st.markdown("### Stream Performance Ranking")
        st.dataframe(build_rankings(filtered, unit_label), use_container_width=True)

        st.markdown("### Whole-Grade Ranking (Best to Worst) & Stream Downloads")
        default_block = selected_grade if selected_grade in GRADES else "Grade 8"
        chosen_block = st.selectbox("Select Block / Grade for Backend Export", GRADES, index=GRADES.index(default_block))
        block_base = df[df["grade"] == chosen_block]
        if selected_term != "All terms":
            block_base = block_base[block_base["term"] == selected_term]
        if selected_exam != "All exams":
            block_base = block_base[block_base["exam"] == selected_exam]

        block_table = build_results_table(block_base, unit_label)
        slug = chosen_block.lower().replace(" ", "_")
        if not block_table.empty:
            rank_cols = [c for c in ["Grade Rank", "Stream Rank", "admission_no", "student_name", "stream", f"Mean ({unit_label})", "Total KNEC Pts", "KNEC Level"] if c in block_table.columns]
            st.markdown(f"#### {chosen_block} Whole-Grade Ranking (1st / Best to Last)")
            st.dataframe(block_table[rank_cols], use_container_width=True)
            st.markdown(f"#### Full {chosen_block} Subject Breakdown")
            st.dataframe(block_table, use_container_width=True)
            st.download_button(f"Download Whole {chosen_block} (CSV)", block_table.to_csv(index=False).encode("utf-8"), f"rwangondu_{slug}_whole.csv", "text/csv")
            s_cols = st.columns(len(STREAMS))
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{slug}_whole.csv", block_table.to_csv(index=False))
                for idx, strm in enumerate(STREAMS):
                    s_df = block_table[block_table["stream"] == strm] if "stream" in block_table.columns else pd.DataFrame()
                    with s_cols[idx]:
                        st.download_button(f"Download {chosen_block} {strm} CSV", s_df.to_csv(index=False).encode("utf-8"), f"rwangondu_{slug}_{strm.lower()}.csv", "text/csv", disabled=s_df.empty)
                    if not s_df.empty:
                        zf.writestr(f"{slug}_{strm.lower()}.csv", s_df.to_csv(index=False))
            zip_buf.seek(0)
            st.download_button(f"Download {chosen_block} Whole + Streams A, B, C (ZIP)", zip_buf.getvalue(), f"rwangondu_{slug}_bundle.zip", "application/zip")
        else:
            st.info(f"No marks found for {chosen_block} under the current Term/Exam filter.")

        with st.expander("Backend Upload History & Data Inspector"):
            st.write({"db": DB_PATH, "roster_count": len(students_df), "marks_rows": len(raw_df), "upload_batches": len(logs_df)})
            if not logs_df.empty:
                st.dataframe(logs_df[["id", "uploaded_at", "upload_type", "source_name", "rows_imported"]], use_container_width=True)
                sel_row = logs_df[logs_df["id"] == st.selectbox("Inspect Uploaded Batch Rows", logs_df["id"].tolist())].iloc[0]
                st.dataframe(pd.read_json(io.StringIO(str(sel_row["preview_json"]))), use_container_width=True)
            else:
                st.info("No uploads logged yet.")
            if not block_table.empty:
                st.download_button(f"Dev Dump: {chosen_block} JSON", block_table.to_json(orient="records", indent=2).encode("utf-8"), f"dev_{slug}.json", "application/json")

        st.markdown("### Grade 9 Recommended Pathways")
        g9_df = filtered[filtered["grade"] == "Grade 9"]
        p_rows: List[dict] = []
        for (adm, sname, stream_val, term_val, exam_val), sdf in g9_df.groupby(["admission_no", "student_name", "stream", "term", "exam"]):
            pm = sdf.groupby("subject")["pct"].mean().to_dict()
            avg_p = float(sdf["pct"].mean())
            hum_p = float(pd.Series([v for k, v in pm.items() if k in HUM_ARTS_SUBJS]).mean())
            p_rows.append({
                "Term": term_val, "Exam": exam_val, "Admission No.": adm, "Learner": sname, "Stream": stream_val,
                f"Mean ({unit_label})": round(float(sdf["display_score"].mean()), 1), "KNEC Level": knec_grade(avg_p)[0],
                "Suggested Pathway": recommend_pathway(avg_p, float(pm.get("Integrated Science", avg_p)), float(pm.get("Pre-Technical Studies", avg_p)), hum_p if pd.notna(hum_p) else avg_p),
            })
        if p_rows:
            pdf_p = pd.DataFrame(p_rows)
            st.image(make_chart(pdf_p["Suggested Pathway"].value_counts().sort_values(), "Grade 9 Recommended Pathways", "Learners", kind="barh", figsize=(10, 3.2)))
            st.dataframe(pdf_p, use_container_width=True)
        else:
            st.info("No Grade 9 marks in the current filter view.")

with tab2:
    st.subheader("Direct Mark Entry")
    e1, e2, e3, e4, e5 = st.columns(5)
    entry_term, entry_exam = e1.selectbox("Term", TERMS, key="e_term"), e2.selectbox("Exam", EXAMS, key="e_exam")
    entry_grade, entry_stream = e3.selectbox("Grade", GRADES, key="e_grade"), e4.selectbox("Stream", STREAMS, key="e_stream")
    max_marks_val = float(e5.number_input("Max Marks (Out Of)", 1.0, 500.0, 100.0, 5.0, key="e_max"))
    class_roster = students_df[(students_df["grade"] == entry_grade) & (students_df["stream"] == entry_stream)]
    if class_roster.empty:
        st.warning(f"No learners in roster for {entry_grade} {entry_stream}.")
    else:
        labels = [f"{r.admission_no} — {r.student_name} ({r.parent_whatsapp})" for r in class_roster.itertuples()]
        chosen_s = class_roster.iloc[st.selectbox("Select Learner", range(len(labels)), format_func=lambda i: labels[i])]
        with st.form("marks_form"):
            st.markdown(f"**{chosen_s['student_name']}** (`{chosen_s['admission_no']}`) — Out of `{max_marks_val:.0f}`")
            marks_in: Dict[str, float] = {}
            cols = st.columns(3)
            for i, subj in enumerate(SUBJECTS):
                with cols[i % 3]:
                    marks_in[subj] = float(st.number_input(f"{subj} (/{max_marks_val:.0f})", 0.0, max_marks_val, 0.0, 1.0, key=f"m_{subj}"))
            if st.form_submit_button("Save Exam Marks"):
                m_rows = [(entry_term, entry_exam, str(chosen_s["grade"]), str(chosen_s["stream"]), str(chosen_s["admission_no"]), subj, sc, max_marks_val) for subj, sc in marks_in.items()]
                upsert_marks(m_rows)
                log_upload("Single Marks Entry", f"{chosen_s['admission_no']} ({entry_exam})", len(m_rows), pd.DataFrame(m_rows, columns=["term", "exam", "grade", "stream", "admission_no", "subject", "score", "max_marks"]))
                st.session_state.db_version += 1
                st.success(f"Saved {entry_exam} marks for {chosen_s['student_name']}.")
                st.rerun()

with tab3:
    st.subheader("Learner Roster & Bulk CSV / Excel Upload")
    st.dataframe(students_df, use_container_width=True)
    with st.form("add_student"):
        a1, a2, a3, a4, a5 = st.columns(5)
        n_adm, n_name = a1.text_input("Admission No.", placeholder="RWG-905"), a2.text_input("Full Name", placeholder="Grace Akinyi")
        n_g, n_s = a3.selectbox("Grade", GRADES, key="n_g"), a4.selectbox("Stream", STREAMS, key="n_s")
        n_wa = a5.text_input("Parent WhatsApp", placeholder="+2547XXXXXXXX")
        if st.form_submit_button("Save Learner"):
            if n_adm.strip() and n_name.strip() and n_wa.strip():
                s_row = [(n_adm.strip(), n_name.strip(), n_g, n_s, n_wa.strip())]
                upsert_students(s_row)
                log_upload("Single Learner", n_adm.strip(), 1, pd.DataFrame(s_row, columns=["admission_no", "student_name", "grade", "stream", "parent_whatsapp"]))
                st.session_state.db_version += 1
                st.success("Learner saved.")
                st.rerun()
            else:
                st.error("Fill in Admission No., Full Name, and Parent WhatsApp.")

    r_tpl = pd.DataFrame([{"admission_no": "RWG-910", "student_name": "Daniel Kipkoech", "grade": "Grade 9", "stream": "A", "parent_whatsapp": "+254712000910"}])
    st.download_button("Download Roster Template", r_tpl.to_csv(index=False).encode("utf-8"), "roster_template.csv", "text/csv")
    r_up = st.file_uploader("Upload Roster (.csv or .xlsx)", type=["csv", "xlsx"], key="r_up")
    if r_up and st.button("Import Roster"):
        up_df = read_file(r_up)
        req = {"admission_no", "student_name", "grade", "stream", "parent_whatsapp"}
        if req.issubset(up_df.columns):
            s_rows = [(str(r["admission_no"]).strip(), str(r["student_name"]).strip(), str(r["grade"]).strip(), str(r["stream"]).strip(), str(r["parent_whatsapp"]).strip()) for _, r in up_df.iterrows()]
            upsert_students(s_rows)
            log_upload("Bulk Roster", r_up.name, len(s_rows), up_df)
            st.session_state.db_version += 1
            st.success(f"Imported {len(s_rows)} learners.")
            st.rerun()
        else:
            st.error(f"Missing columns: {sorted(req)}")

    def_max = float(st.number_input("Default Max Marks (if `max_marks` column omitted)", 1.0, 500.0, 100.0, 5.0))
    m_tpl = pd.DataFrame([{"term": "Term 1", "exam": "Mid-Term", "admission_no": "RWG-901", "max_marks": 50, "Mathematics": 34, "English": 36}])
    st.download_button("Download Marks Template", m_tpl.to_csv(index=False).encode("utf-8"), "marks_template.csv", "text/csv")
    m_up = st.file_uploader("Upload Marks (.csv or .xlsx)", type=["csv", "xlsx"], key="m_up")
    if m_up and st.button("Import Marks"):
        try:
            mdf = read_file(m_up)
            parsed = parse_bulk_marks(mdf, students_df.set_index("admission_no")[["grade", "stream"]].to_dict("index"), def_max)
            if parsed:
                upsert_marks(parsed)
                log_upload("Bulk Marks", m_up.name, len(parsed), mdf)
                st.session_state.db_version += 1
                st.success(f"Imported {len(parsed)} mark rows.")
                st.rerun()
            else:
                st.warning("No matching admission numbers found in roster.")
        except Exception as err:
            st.error(str(err))

with tab4:
    st.subheader("PDF Report & Parent Messaging")
    if df.empty:
        st.info("No marks recorded yet.")
    else:
        roster_m = df[["admission_no", "student_name", "grade", "stream", "term", "parent_whatsapp"]].drop_duplicates()
        opts = [f"{r.admission_no} — {r.student_name} ({r.grade} {r.stream}, {r.term})" for r in roster_m.itertuples()]
        row = roster_m.iloc[st.selectbox("Select Learner & Term", range(len(opts)), format_func=lambda i: opts[i])]

        sdf = df[(df["admission_no"] == row["admission_no"]) & (df["term"] == row["term"])]
        exam_opts = ["All Exams"] + sorted(sdf["exam"].unique().tolist())
        chosen_ex = st.selectbox("Exam Scope", exam_opts)
        if chosen_ex != "All Exams":
            sdf = sdf[sdf["exam"] == chosen_ex]

        pm = sdf.groupby("subject")["pct"].mean().to_dict()
        avg_p = float(sdf["pct"].mean())
        hum_p = float(pd.Series([v for k, v in pm.items() if k in HUM_ARTS_SUBJS]).mean())
        pathway = recommend_pathway(avg_p, float(pm.get("Integrated Science", avg_p)), float(pm.get("Pre-Technical Studies", avg_p)), hum_p if pd.notna(hum_p) else avg_p)
        lvl_str, pts_val, _ = knec_grade(avg_p)

        chart_png = make_chart(sdf.groupby("subject")["display_score"].mean().sort_values(), f"{row['student_name']} — Subjects ({unit_label})", f"Score ({unit_label})", 100.0 if convert_to_pct else None, "barh", (7.2, 3.8))
        st.image(chart_png)

        os.makedirs("term_reports", exist_ok=True)
        pdf_path = os.path.join("term_reports", f"{row['admission_no']}_{str(row['term']).replace(' ', '_')}_{chosen_ex.replace(' ', '_')}.pdf")
        if st.button("Generate PDF Report"):
            try:
                pdf_bytes = generate_pdf(str(row["student_name"]), str(row["admission_no"]), str(row["grade"]), str(row["stream"]), str(row["term"]), chosen_ex, pathway, unit_label, sdf, chart_png)
                with open(pdf_path, "wb") as f:
                    f.write(pdf_bytes)
                st.download_button("Download PDF", pdf_bytes, os.path.basename(pdf_path), "application/pdf")
                st.success(f"Saved {pdf_path}")
            except Exception as err:
                st.error(str(err))

        mean_disp = float(sdf["display_score"].mean())
        base_msg = f"Rwang'ondu School ({row['term']} - {chosen_ex}): {row['student_name']} ({row['grade']} {row['stream']}) mean {mean_disp:.1f} {unit_label} [{lvl_str}, {pts_val}pt]." + (f" Pathway: {pathway}." if row["grade"] == "Grade 9" else "")
        mode = st.radio("Send Option", ["WhatsApp", "Alternative Message (SMS / Custom)"], horizontal=True)
        msg_txt = st.text_area("Message", value=base_msg, height=80)
        if mode == "WhatsApp":
            wa_link = f"https://wa.me/{''.join(ch for ch in str(row['parent_whatsapp']) if ch.isdigit())}?text={urllib.parse.quote(msg_txt)}"
            st.markdown(f"[Open WhatsApp]({wa_link})")
        if st.button("Queue Message"):
            st.info(f"[{mode}] To {row['parent_whatsapp']}: {msg_txt}")