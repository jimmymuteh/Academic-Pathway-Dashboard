# Rwang'ondu School Academic & Pathway Portal

As a Junior School teacher, I built this app to solve a real end-of-term headache: collecting marks from different teachers across Grades 7–9, figuring out Grade 9 Senior School pathways without spending days in spreadsheets, and getting clean progress reports to parents on WhatsApp.

Instead of typing student names and admission numbers over and over for every exam, the app stores the learner roster once in a local SQLite database (`rwang'ondu_school.db`) and lets teachers record scores across **Opener, Mid-Term, End-Month, and End-Term** exams.

## How It Works in Practice

1. **Learner Roster & Bulk Uploads:** You add learners once (individually or via a CSV/Excel sheet) along with their grade, stream (A, B, or C), and parent WhatsApp contact.
2. **Direct Mark Entry:** Teachers pick a term, exam, class, and learner from a dropdown and enter scores for the **9 Junior School learning areas** (Mathematics, English, Kiswahili, Integrated Science, Social Studies, Pre-Technical Studies, Agriculture, Creative Arts & Sports, and Religious Education).
3. **Stream & Pathway Analysis:** The dashboard filters performance by term, exam, grade, and stream using Matplotlib charts, and flags suggested Senior School pathways (STEM, Social Sciences & Humanities, or Arts & Sports Science) for Grade 9 learners.
4. **End-of-Term PDFs & WhatsApp Summaries:** Generates an individual PDF report card with a subject performance chart saved to `term_reports/` and drafts a summary message ready for parent WhatsApp outreach.