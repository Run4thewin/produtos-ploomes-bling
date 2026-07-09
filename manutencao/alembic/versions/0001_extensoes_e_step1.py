"""extensoes + step1 (empresa, perfil, permissao, usuario)

Revision ID: 0001
Revises:
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UUID = postgresql.UUID(as_uuid=True)
_UUID_DEFAULT = sa.text("gen_random_uuid()")
_NOW = sa.text("now()")


def upgrade() -> None:
    # gen_random_uuid() vem da extensão pgcrypto.
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    op.create_table(
        "empresa",
        sa.Column("id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("razao_social", sa.String(200), nullable=False),
        sa.Column("nome_fantasia", sa.String(200)),
        sa.Column("cnpj", sa.String(18), nullable=False),
        sa.Column("segmento", sa.String(100)),
        sa.Column("endereco", sa.String(300)),
        sa.Column("cidade", sa.String(100)),
        sa.Column("uf", sa.String(2)),
        sa.Column("cep", sa.String(9)),
        sa.Column("telefone", sa.String(20)),
        sa.Column("email", sa.String(150)),
        sa.Column("logo_url", sa.String(500)),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("cnpj", name="uq_empresa_cnpj"),
    )

    op.create_table(
        "perfil",
        sa.Column("id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("nome", sa.String(60), nullable=False),
        sa.Column("descricao", sa.String(200)),
        sa.Column("nivel_acesso", sa.SmallInteger, nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )

    op.create_table(
        "permissao",
        sa.Column("id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("perfil_id", _UUID, sa.ForeignKey("perfil.id"), nullable=False),
        sa.Column("modulo", sa.String(60), nullable=False),
        sa.Column("pode_criar", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("pode_ler", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("pode_editar", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("pode_excluir", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("perfil_id", "modulo", name="uq_permissao_perfil_modulo"),
    )

    op.create_table(
        "usuario",
        sa.Column("id", _UUID, primary_key=True, server_default=_UUID_DEFAULT),
        sa.Column("empresa_id", _UUID, sa.ForeignKey("empresa.id"), nullable=False),
        sa.Column("perfil_id", _UUID, sa.ForeignKey("perfil.id"), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("senha_hash", sa.String(255), nullable=False),
        sa.Column("telefone", sa.String(20)),
        sa.Column("cargo", sa.String(100)),
        sa.Column("foto_url", sa.String(500)),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("ultimo_login", sa.DateTime(timezone=True)),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("email", name="uq_usuario_email"),
    )
    op.create_index("ix_usuario_empresa_id", "usuario", ["empresa_id"])


def downgrade() -> None:
    op.drop_index("ix_usuario_empresa_id", table_name="usuario")
    op.drop_table("usuario")
    op.drop_table("permissao")
    op.drop_table("perfil")
    op.drop_table("empresa")
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto";')
