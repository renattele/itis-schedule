"""
Module to handle student-specific elective choices.
"""

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import requests
from openpyxl import load_workbook

# URL for the Student Choices Google Sheet (CSV export)
CHOICES_URL_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
)

# Standard columns in the choices sheet
COL_NAME = "ФИО"
COL_GROUP = "Группа"
# We ignore 5th sem
COL_TECH_BLOCK_6 = "Технологический блок (6 семестр)"
COL_SCI_BLOCK_6 = "Научный блок (6 семестр)"

@dataclass
class StudentChoice:
    name: str
    group: str
    tech_block: str
    sci_block: str

def fetch_choices(spreadsheet_id: str, gid: str = "0") -> List[StudentChoice]:
    """Fetch and parse student elective choices."""
    url = CHOICES_URL_TEMPLATE.format(spreadsheet_id=spreadsheet_id, gid=gid)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    
    # Check encoding - Google Sheets CSV is usually UTF-8
    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    
    students = []
    for row in reader:
        # Check if row has necessary columns
        if not row.get(COL_NAME) or not row.get(COL_GROUP):
            continue
            
        students.append(StudentChoice(
            name=row[COL_NAME].strip(),
            group=row[COL_GROUP].strip(),
            tech_block=row.get(COL_TECH_BLOCK_6, "").strip(),
            sci_block=row.get(COL_SCI_BLOCK_6, "").strip()
        ))
    return students

def normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching (lowercase, remove punctuation)."""
    # Replace punctuation with spaces to avoid joining words (e.g. Devops/SRE -> devops sre)
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())

def extract_keywords(choice_str: str) -> Set[str]:
    """Extract significant keywords from a choice string."""
    # 1. Remove block names in parentheses to avoid matching generic block terms
    # e.g. "Django (Технологии разработки...) – Дубровец В.О." -> "Django – Дубровец В.О."
    clean_choice = re.sub(r"\(.*?\)", "", choice_str)
    
    # 2. Normalize and tokenize
    norm = normalize_text(clean_choice)
    tokens = set(norm.split())
    
    # 3. Remove common words
    ignore = {
        "технологии", "разработки", "разработка", "по", "для", "начинающих", 
        "доп", "главы", "блок", "семестр", "прикладные", "задачи", 
        "интеллектуального", "анализа", "данных", "на", "основы", 
        "программного", "обеспечения", "систем", "управлению", "управление"
    }
    # 3. Remove common words and short tokens (initials/prepositions)
    ignore = {
        "технологии", "разработки", "разработка", "по", "для", "начинающих", 
        "доп", "главы", "блок", "семестр", "прикладные", "задачи", 
        "интеллектуального", "анализа", "данных", "на", "основы", 
        "программного", "обеспечения", "систем", "управлению", "управление",
        "приложений", "приложения", "приложение", "часть", "часть1", "часть2",
        "мобильных", "архитектура", "проектирование", "занятия", "вебинар",
        "вебинары", "дисциплина", "дисциплины", "выбору"
    }
    return {t for t in tokens if t not in ignore and len(t) > 2}

def find_elective_match(choice: str, available_lessons: List['Lesson']) -> List['Lesson']:
    """Find scheduled lessons matching the user's choice string."""
    if not choice:
        return []

    # Strategy:
    # 1. Extract potential instructor surname from choice (usually ends with '– Surname I.O.')
    # 2. Extract keywords.
    
    # Try to find instructor pattern "Name I.O." or "Surname"
    # In choice string: "Subject – Surname I.O."
    instructor_match = re.search(r"[–-]\s*([А-ЯЁ][а-яё]+)\s+[А-ЯЁ]\.", choice)
    instructor_surname = ""
    if instructor_match:
        instructor_surname = instructor_match.group(1).lower()
    
    keywords = extract_keywords(choice)
    matches = []
    
    for lesson in available_lessons:
        # Check against lesson subject + instructor + notes
        lesson_text = normalize_text(f"{lesson.subject} {lesson.instructor} {lesson.notes}")
        # Apply the same keyword extraction filter to the lesson text for consistency
        # This re-uses the extract_keywords logic (splitting + ignoring + min length)
        lesson_tokens = extract_keywords(lesson_text)
        
        # Instructor match is strongest signal
        if instructor_surname and instructor_surname in lesson_tokens:
            matches.append(lesson)
            continue
            
        # Keyword match
        # We use set intersection for higher precision
        if keywords.intersection(lesson_tokens):
            matches.append(lesson)
    
    return matches
