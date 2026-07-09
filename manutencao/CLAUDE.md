# CLAUDE.md — Aplicativo de Manutenção (Backend + Banco de Dados)

Este arquivo orienta o Claude Code no desenvolvimento do backend. Leia por completo antes de
implementar qualquer função. A especificação funcional completa (55 funções, PF e horas) está
em `docs/APF_Aplicativo_Manutencao.xlsx`, abas "Funcoes Detalhadas" e "Entidades (ALI)".

## Visão geral do projeto

App de gestão de manutenção industrial (equipamentos, ordens de serviço, estoque de
lubrificantes, relatórios, e em V2: IA sobre manuais técnicos, agendamento preventivo e
notificações). Multiempresa (multi-tenant por `empresa_id`).

## Stack

- **Linguagem**: Python 3.12+
- **Framework**: FastAPI
- **ORM**: SQLAlchemy 2.x, modo **assíncrono** (asyncio + `asyncpg`)
- **Banco**: PostgreSQL 16+
- **Migrações**: Alembic
- **Validação**: Pydantic v2 (schemas separados de models ORM)
- **Auth**: JWT (access + refresh token), hash de senha com `passlib[bcrypt]`
- **Fila/Job agendado** (V2 — notificações, agendamento): `APScheduler` ou Celery + Redis (decidir
  conforme volume; para V1 não é necessário)
- **Armazenamento de arquivos**: local em dev, S3-compatível (ex: Cloudflare R2/AWS S3) em produção
- **Testes**: pytest + pytest-asyncio + httpx (test client assíncrono)

## Estrutura de pastas

```
app/
  core/           # config, security (JWT/hash), settings via pydantic-settings
  db/
    base.py       # Base declarativa, engine, async session factory
    session.py    # get_db() dependency
  models/         # SQLAlchemy ORM models (1 arquivo por entidade)
  schemas/        # Pydantic schemas (Create/Update/Read por entidade)
  repositories/   # acesso a dados (queries async), 1 por entidade
  services/       # regras de negócio (ex: baixa automática de estoque)
  api/
    v1/
      routers/    # 1 router por módulo (usuarios, equipamentos, manutencoes, ...)
      deps.py     # dependencies comuns (get_current_user, checar permissão)
  main.py
alembic/
  versions/
tests/
docs/
  APF_Aplicativo_Manutencao.xlsx
```

## Convenções de nomenclatura

- Tabelas e colunas em **snake_case, português**, seguindo os nomes das entidades da planilha
  (`equipamento`, `manutencao`, `movimentacao_estoque`, etc.) — mesma convenção usada no Commanda.
- Toda tabela tem: `id` (UUID, `gen_random_uuid()`), `criado_em`, `atualizado_em`
  (`timestamptz`, default `now()`), `ativo` (boolean, default `true`, para soft delete) — exceto
  onde indicado.
- Toda tabela operacional (exceto `empresa`, `perfil`) tem `empresa_id` (FK) para isolamento
  multi-tenant. Toda query de listagem/consulta DEVE filtrar por `empresa_id` do usuário logado.
- Enums de domínio como `VARCHAR` + `CHECK constraint` (não usar enum nativo do Postgres, para
  facilitar evolução sem migração de tipo).

## Modelo de dados (DDL de referência)

Implementar via Alembic, uma migração por entidade, respeitando a ordem de dependência abaixo.

### 1. `empresa`
```sql
id UUID PK
razao_social VARCHAR(200) NOT NULL
nome_fantasia VARCHAR(200)
cnpj VARCHAR(18) NOT NULL UNIQUE
segmento VARCHAR(100)
endereco VARCHAR(300)
cidade VARCHAR(100)
uf CHAR(2)
cep VARCHAR(9)
telefone VARCHAR(20)
email VARCHAR(150)
logo_url VARCHAR(500)
ativo BOOLEAN DEFAULT true
criado_em, atualizado_em
```

### 2. `perfil`
```sql
id UUID PK
nome VARCHAR(60) NOT NULL         -- ex: Admin, Técnico, Gestor
descricao VARCHAR(200)
nivel_acesso SMALLINT NOT NULL    -- 1=admin, 2=gestor, 3=técnico, 4=leitura
criado_em, atualizado_em
```
> `perfil` é global (não tem `empresa_id`) — perfis padrão do sistema. Se precisar de perfis
> customizados por empresa, adicionar `empresa_id` nullable (null = perfil padrão do sistema).

### 3. `permissao`
```sql
id UUID PK
perfil_id UUID FK -> perfil.id NOT NULL
modulo VARCHAR(60) NOT NULL        -- ex: equipamentos, manutencoes, estoque
pode_criar BOOLEAN DEFAULT false
pode_ler BOOLEAN DEFAULT true
pode_editar BOOLEAN DEFAULT false
pode_excluir BOOLEAN DEFAULT false
UNIQUE (perfil_id, modulo)
```

### 4. `usuario`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
perfil_id UUID FK -> perfil.id NOT NULL
nome VARCHAR(150) NOT NULL
email VARCHAR(150) NOT NULL UNIQUE
senha_hash VARCHAR(255) NOT NULL
telefone VARCHAR(20)
cargo VARCHAR(100)
foto_url VARCHAR(500)
ativo BOOLEAN DEFAULT true
ultimo_login TIMESTAMPTZ
criado_em, atualizado_em
INDEX (empresa_id)
```

### 5. `equipamento`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
tag VARCHAR(50) NOT NULL           -- identificação física do ativo
nome VARCHAR(150) NOT NULL
categoria VARCHAR(100)
fabricante VARCHAR(100)
modelo VARCHAR(100)
numero_serie VARCHAR(100)
localizacao VARCHAR(150)
setor VARCHAR(100)
data_instalacao DATE
vida_util_meses INTEGER
capacidade VARCHAR(50)
foto_principal_url VARCHAR(500)
status VARCHAR(20) DEFAULT 'ativo' CHECK (status IN ('ativo','em_manutencao','inativo','baixado'))
criado_em, atualizado_em
UNIQUE (empresa_id, tag)
INDEX (empresa_id, status)
```

### 6. `arquivo`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
entidade_tipo VARCHAR(40) NOT NULL   -- 'equipamento', 'manutencao', 'evidencia', 'manual_servico'
entidade_id UUID NOT NULL            -- FK polimórfica (validada em app, não em DB)
nome_original VARCHAR(255) NOT NULL
tipo_mime VARCHAR(100)
tamanho_bytes BIGINT
url VARCHAR(500) NOT NULL
enviado_por UUID FK -> usuario.id
criado_em
INDEX (entidade_tipo, entidade_id)
```

### 7. `manutencao`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
equipamento_id UUID FK -> equipamento.id NOT NULL
tecnico_id UUID FK -> usuario.id
tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('preventiva','corretiva','preditiva'))
prioridade VARCHAR(10) DEFAULT 'media' CHECK (prioridade IN ('baixa','media','alta','critica'))
status VARCHAR(20) DEFAULT 'aberta' CHECK (status IN ('aberta','em_execucao','concluida','cancelada'))
descricao TEXT
checklist JSONB                    -- lista de itens verificados
horimetro NUMERIC(10,2)
data_abertura TIMESTAMPTZ DEFAULT now()
data_execucao TIMESTAMPTZ
data_conclusao TIMESTAMPTZ
tempo_gasto_minutos INTEGER
custo_mao_obra NUMERIC(12,2)
motivo_cancelamento VARCHAR(300)
criado_em, atualizado_em
INDEX (empresa_id, equipamento_id, status)
INDEX (empresa_id, data_abertura)
```

### 8. `manutencao_peca` (itens/peças usados na OS — sub-tabela citada na dissecação)
```sql
id UUID PK
manutencao_id UUID FK -> manutencao.id NOT NULL
descricao VARCHAR(150) NOT NULL
quantidade NUMERIC(10,2) NOT NULL
custo_unitario NUMERIC(12,2)
```

### 9. `evidencia`
```sql
id UUID PK
manutencao_id UUID FK -> manutencao.id NOT NULL
arquivo_id UUID FK -> arquivo.id NOT NULL
descricao VARCHAR(200)
criado_em
```

### 10. `relatorio`
```sql
id UUID PK
manutencao_id UUID FK -> manutencao.id NOT NULL
formato VARCHAR(10) DEFAULT 'pdf'
url_arquivo VARCHAR(500)
gerado_por UUID FK -> usuario.id
criado_em
```

### 11. `lubrificante`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
nome VARCHAR(150) NOT NULL
codigo VARCHAR(50)
fabricante VARCHAR(100)
unidade_medida VARCHAR(10) NOT NULL   -- L, KG, UN
preco_unitario NUMERIC(12,2)
estoque_minimo NUMERIC(10,2) DEFAULT 0
ficha_tecnica_url VARCHAR(500)
ativo BOOLEAN DEFAULT true
criado_em, atualizado_em
UNIQUE (empresa_id, codigo)
```

### 12. `estoque`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
lubrificante_id UUID FK -> lubrificante.id NOT NULL
localizacao VARCHAR(100)
quantidade_atual NUMERIC(10,2) NOT NULL DEFAULT 0
atualizado_em TIMESTAMPTZ DEFAULT now()
UNIQUE (empresa_id, lubrificante_id, localizacao)
```
> `quantidade_atual` é sempre derivada de `movimentacao_estoque` — nunca editar diretamente via
> API; recalcular via trigger ou dentro da mesma transação do service que grava a movimentação.

### 13. `movimentacao_estoque`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
estoque_id UUID FK -> estoque.id NOT NULL
tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('entrada','saida'))
quantidade NUMERIC(10,2) NOT NULL CHECK (quantidade > 0)
motivo VARCHAR(30) NOT NULL CHECK (motivo IN ('compra','consumo_os','ajuste','devolucao'))
manutencao_id UUID FK -> manutencao.id           -- preenchido quando motivo = consumo_os
fornecedor VARCHAR(150)
nota_fiscal VARCHAR(50)
valor_total NUMERIC(12,2)
responsavel_id UUID FK -> usuario.id NOT NULL
criado_em TIMESTAMPTZ DEFAULT now()
INDEX (empresa_id, estoque_id, criado_em)
```

### 14. `manual_servico`
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
equipamento_id UUID FK -> equipamento.id NOT NULL
arquivo_id UUID FK -> arquivo.id NOT NULL
versao VARCHAR(20)
indexado BOOLEAN DEFAULT false     -- true após processamento de embeddings (V2)
criado_em
```

### 15. `manual_servico_chunk` (V2 — necessário para RAG do chat IA)
```sql
id UUID PK
manual_servico_id UUID FK -> manual_servico.id NOT NULL
pagina INTEGER
conteudo TEXT NOT NULL
embedding VECTOR(1536)             -- requer extensão pgvector
INDEX ivfflat/hnsw (embedding)
```

### 16. `chat_ia` (V2)
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
usuario_id UUID FK -> usuario.id NOT NULL
manual_servico_id UUID FK -> manual_servico.id
sessao_id UUID NOT NULL
pergunta TEXT NOT NULL
resposta TEXT
paginas_citadas INTEGER[]
criado_em TIMESTAMPTZ DEFAULT now()
INDEX (usuario_id, sessao_id)
```

### 17. `agendamento` (V2)
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
equipamento_id UUID FK -> equipamento.id NOT NULL
tipo VARCHAR(20) DEFAULT 'preventiva'
data_prevista DATE NOT NULL
recorrencia VARCHAR(20)            -- 'unica','semanal','mensal','anual'
responsavel_id UUID FK -> usuario.id
checklist JSONB
status VARCHAR(20) DEFAULT 'pendente' CHECK (status IN ('pendente','gerada','cancelada'))
motivo_cancelamento VARCHAR(300)
criado_em, atualizado_em
INDEX (empresa_id, data_prevista, status)
```

### 18. `alerta_regra` (V2)
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
gatilho VARCHAR(40) NOT NULL CHECK (gatilho IN ('os_atrasada','estoque_minimo','agendamento_proximo'))
parametros JSONB
canal VARCHAR(10) DEFAULT 'push' CHECK (canal IN ('push','email'))
ativo BOOLEAN DEFAULT true
criado_em
```

### 19. `notificacao` (V2)
```sql
id UUID PK
empresa_id UUID FK -> empresa.id NOT NULL
usuario_id UUID FK -> usuario.id NOT NULL
titulo VARCHAR(150) NOT NULL
mensagem VARCHAR(500)
lida BOOLEAN DEFAULT false
criado_em TIMESTAMPTZ DEFAULT now()
INDEX (usuario_id, lida)
```

## Arquitetura em camadas (obrigatório)

Toda funcionalidade segue estritamente 4 camadas, sem pular etapa e sem misturar responsabilidade:

```
Router (api/v1/routers)
   -> recebe request, valida com Pydantic, extrai usuario/empresa autenticados
   -> chama Service — NUNCA acessa repository ou session diretamente
        |
        v
Service (services/)
   -> regra de negócio, orquestra 1+ repositories, controla transação
   -> ex: consumir lubrificante = repo de manutencao + repo de estoque + repo de movimentacao,
      tudo dentro da mesma transação
        |
        v
Repository (repositories/)
   -> ÚNICA camada que constrói queries SQLAlchemy e toca a AsyncSession
   -> 1 arquivo por entidade, métodos objeto-orientados (get_by_id, list_by_equipamento,
      create, update, soft_delete) — nunca métodos genéricos "execute_query"
        |
        v
Model (models/) — classes ORM (SQLAlchemy declarative), com relationship() mapeado
```

Regras rígidas:
- **Router nunca importa `Session`/`AsyncSession` nem monta query** — só chama método de Service.
- **Service nunca monta `select()`** — só chama métodos de Repository e orquestra a transação.
- **Repository é o único lugar que escreve `select`, `insert`, `update`, `join`** — via SQLAlchemy
  ORM (Core 2.0 style), nunca SQL cru.
- Isso garante que trocar de banco, adicionar cache, ou testar regra de negócio com mock de
  repository funcione sem tocar nas outras camadas — é o que garante a arquitetura limpa.

### Relacionamentos e joins — sempre via ORM, nunca SQL puro

- Toda FK do modelo de dados vira um `relationship()` no model, com `back_populates` nos dois
  lados. Exemplo (`manutencao` ↔ `equipamento` ↔ `usuario`):

```python
# models/equipamento.py
class Equipamento(Base):
    __tablename__ = "equipamento"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    empresa_id: Mapped[UUID] = mapped_column(ForeignKey("empresa.id"))
    tag: Mapped[str]
    nome: Mapped[str]
    manutencoes: Mapped[list["Manutencao"]] = relationship(back_populates="equipamento")

# models/manutencao.py
class Manutencao(Base):
    __tablename__ = "manutencao"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    equipamento_id: Mapped[UUID] = mapped_column(ForeignKey("equipamento.id"))
    tecnico_id: Mapped[UUID | None] = mapped_column(ForeignKey("usuario.id"))
    equipamento: Mapped["Equipamento"] = relationship(back_populates="manutencoes")
    tecnico: Mapped["Usuario | None"] = relationship()
    pecas: Mapped[list["ManutencaoPeca"]] = relationship(back_populates="manutencao", cascade="all, delete-orphan")
```

- **Join** (cruzamento de dados) é sempre resolvido com `select()` + `.join()` do SQLAlchemy, ou
  com eager loading (`selectinload`/`joinedload`) quando o objetivo é carregar relacionamentos
  junto — nunca com `text("SELECT ... JOIN ...")`:

```python
# repositories/manutencao.py — join explícito com filtro
async def listar_por_equipamento(session: AsyncSession, empresa_id: UUID, equipamento_id: UUID):
    stmt = (
        select(Manutencao)
        .join(Manutencao.equipamento)
        .options(selectinload(Manutencao.tecnico), selectinload(Manutencao.pecas))
        .where(
            Manutencao.empresa_id == empresa_id,
            Manutencao.equipamento_id == equipamento_id,
        )
        .order_by(Manutencao.data_abertura.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()
```

- Consultas agregadas (ex: dashboard) usam `func.count()`, `func.sum()` do SQLAlchemy sobre o
  `select()`, com `.group_by()` — não usar SQL cru nem processar agregação em Python depois de
  trazer todas as linhas.
- `JSONB` (ex: `checklist`) é mapeado com `Mapped[dict]` / `Mapped[list]` usando o tipo
  `JSONB` do SQLAlchemy (`sqlalchemy.dialects.postgresql.JSONB`), não como string.
- Proibido usar `session.execute(text(...))` em qualquer camada, exceto migrações Alembic e
  scripts pontuais de manutenção de dados fora da aplicação.

## Padrão de API (FastAPI)

- Prefixo `/api/v1/{modulo}`, plural em português (`/equipamentos`, `/manutencoes`).
- Verbos padrão REST: `POST` incluir, `PUT`/`PATCH` alterar, `DELETE` inativar (soft delete —
  seta `ativo=false`, nunca `DELETE` físico em entidades operacionais), `GET` consultar
  (com paginação `?page=&page_size=` e filtros por query params).
- Toda rota autenticada via `Depends(get_current_user)`; checagem de permissão por módulo via
  dependency `require_permission("equipamentos", "editar")` lendo a tabela `permissao`.
- Toda rota filtra automaticamente por `empresa_id` do usuário logado (nunca aceitar
  `empresa_id` vindo do client em rotas de escrita).
- Schemas Pydantic: `{Entidade}Create`, `{Entidade}Update` (todos campos opcionais),
  `{Entidade}Read` (inclui `id`, timestamps).
- Regra de negócio que envolve mais de uma tabela (ex: consumir lubrificante → gera
  `movimentacao_estoque` e recalcula `estoque.quantidade_atual`) fica em `services/`, dentro de
  uma única transação (`async with session.begin()`), nunca no router.

## Sessão async — padrão obrigatório

```python
# db/session.py
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

A `AsyncSession` só é injetada no **Router** (via `Depends(get_db)`) e passada adiante — Router
entrega a session para o Service, Service entrega para o(s) Repository(ies) que chamar. Repository
é quem efetivamente executa `session.execute(...)`/`session.add(...)`. Ver exemplos completos na
seção "Arquitetura em camadas" acima.

## Ordem de implementação recomendada (respeita FKs e prioridade V1)

1. `empresa`, `perfil`, `permissao`, `usuario` + autenticação (login/JWT/recuperação de senha)
2. `equipamento` + `arquivo` (anexos)
3. `lubrificante`, `estoque`, `movimentacao_estoque`
4. `manutencao`, `manutencao_peca`, `evidencia`, `relatorio` (inclui consumo de lubrificante
   integrado com `movimentacao_estoque`)
5. Dashboard (endpoints agregados de consulta — sem tabela própria, usa queries agregadas)
6. **V2**: `manual_servico`, `manual_servico_chunk`, `chat_ia` (RAG), `agendamento`,
   `alerta_regra`, `notificacao`

Use a planilha `docs/APF_Aplicativo_Manutencao.xlsx` (aba "Funcoes Detalhadas") como checklist —
cada linha é uma função a implementar; ao concluir, pode marcar na coluna que quiser adicionar.

## Migrações (Alembic)

- Uma revisão por entidade/grupo relacionado, mensagem descritiva (`alembic revision --autogenerate -m "cria tabela equipamento"`).
- Sempre revisar o autogenerate antes de aplicar — SQLAlchemy async + Alembic exige engine
  síncrono só para migração (configurar `sqlalchemy.url` com driver `psycopg` no `alembic.ini`,
  mesmo que a app use `asyncpg`).
- Extensões necessárias: `CREATE EXTENSION IF NOT EXISTS "pgcrypto";` (para `gen_random_uuid()`)
  e `CREATE EXTENSION IF NOT EXISTS vector;` (pgvector, só quando chegar em V2/IA).

## Testes

- Um teste de integração por endpoint principal (happy path + 1 caso de erro de permissão/
  validação), usando banco de teste (schema separado ou container descartável).
- Rodar `pytest` antes de qualquer commit; corrigir falhas antes de prosseguir para a próxima
  função.

## O que NÃO fazer

- Não usar SQL puro (`text("SELECT ...")`) em nenhuma camada da aplicação — todo acesso a dado é
  via SQLAlchemy ORM/Core, com `relationship()` mapeado e `.join()`/`selectinload` para cruzamento
  de dados. Exceção única: migrações Alembic.
- Não deixar Router ou Service montar `select()`/tocar `AsyncSession` diretamente — isso é
  responsabilidade exclusiva do Repository (ver "Arquitetura em camadas").
- Não hardcode `empresa_id` nem pular a checagem multi-tenant em nenhuma query.
- Não usar `DELETE` físico em `equipamento`, `manutencao`, `usuario`, `empresa` — sempre soft
  delete via `ativo=false`.
- Não calcular `estoque.quantidade_atual` em duas rotas diferentes com lógica duplicada — sempre
  via `services/estoque_service.py`.
- Não implementar o módulo de IA (V2) antes do V1 estar funcional e testado.
