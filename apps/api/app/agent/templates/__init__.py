"""The template registry (D13). A plain dict of modules in this repo, reviewed like any code."""
from app.agent.platform import Template
from app.agent.templates import database, documents

TEMPLATES: dict[str, Template] = {e.name: e for e in (documents.TEMPLATE, database.TEMPLATE)}
