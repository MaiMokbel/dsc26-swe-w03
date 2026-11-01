"""Database models. `Base` and `Account` are provided by DSC: do not change them
(migration 0001 creates `accounts` exactly like this).

Add `Transfer` (table `transfers`) and `IdempotencyRecord` (table `idempotency_records`)
below, then write migrations/versions/0002_*.py so that `alembic upgrade head` creates
exactly what these models describe.
"""
### el import el gedid: ForeignKey, Text, UniqueConstraint zayadeen 3ala el adeem
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):  # provided by DSC (migration 0001)
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(32), index=True)
    balance_piastres: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EGP")
    __table_args__ = (CheckConstraint("balance_piastres >= 0", name="ck_accounts_balance_non_negative"),)


### Transfer: el table beta3 el tahweelat, el id lazem yebda2 b "trf_"
class Transfer(Base):
    __tablename__ = "transfers"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ### el 2 foreign keys bel esm el explicit 3ashan el migration yetabe2 tamam
    from_account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", name="fk_transfers_from_account_id_accounts")
    )
    to_account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", name="fk_transfers_to_account_id_accounts")
    )
    amount_piastres: Mapped[int] = mapped_column(Integer)
    memo: Mapped[str | None] = mapped_column(String(140), nullable=True)  ### nullable, mesh lazem memo
    status: Mapped[str] = mapped_column(String(20), default="completed")
    ### el CHECK da beyemna3 amount sefr aw negative (H03)
    __table_args__ = (CheckConstraint("amount_piastres > 0", name="ck_transfers_amount_positive"),)


### IdempotencyRecord: bnekhazen feeha el response 3ashan el retry yetrad nafs el rad
class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(32))   ### zay ma gah bezabt, mat8ayarsh feeh
    key: Mapped[str] = mapped_column(String(255))          
    request_hash: Mapped[str] = mapped_column(String(64))  ### sha256 lel body, 3ashan nakshef lw et8ayar
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)       ### el JSON text elly hanerg3o
    ### unique 3ala (customer, key): kol customer leh keys beta3to lewahdo (H11)
    __table_args__ = (UniqueConstraint("customer_id", "key", name="uq_idempotency_customer_key"),)