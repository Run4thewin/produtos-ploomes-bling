"""Importa todos os models para que Base.metadata seja populada (Alembic/criação de schema)."""
from app.models.empresa import Empresa
from app.models.perfil import Perfil
from app.models.permissao import Permissao
from app.models.usuario import Usuario

__all__ = ["Empresa", "Perfil", "Permissao", "Usuario"]
