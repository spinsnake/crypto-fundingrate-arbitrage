from .adapter import AsterdexAdapter
from .order_management import AsterdexOrderManagement
from .portfolio_management import AsterdexPortfolioManagement
from .executor import AsterdexFutureExecution
from trading_core.core.cex_account_manager import CexAccountManager
from trading_core.core.wallet_model import CryptoAccountCex as AsterdexAccount

AsterdexAccountManager = CexAccountManager

__all__ = [
    'AsterdexAdapter',
    'AsterdexAccount',
    'AsterdexAccountManager',
    'AsterdexOrderManagement',
    'AsterdexPortfolioManagement',
    'AsterdexFutureExecution',
]
