# AI Usage

## Tools

- **Claude:** used as an AI assistant during development to understand the requirements, discuss solutions, review code, and troubleshoot errors.
- **Pytest:** used to run automated tests and verify the API behavior.
- **Hypothesis:** used for property-based testing, generating random transfer operations and checking that money is conserved.
- **VS Code:** used for writing, editing, and debugging the project.

## What AI got wrong

- **Virtual environment activation:** Claude first suggested `source .venv/bin/activate`, which is a Linux/macOS command and did not work in my Windows PowerShell terminal. I had to use `.venv\Scripts\activate` instead.
- **Python command escaping:** Claude gave me a one-line `python -c` command with escaped quotation marks (`\"`). PowerShell handles the escaping differently, so the command failed and the database insert did not run. I fixed this by putting the code in a separate `.py` file.
- **Missing `tests/__init__.py`:** the starter project did not include `tests/__init__.py`, and Claude's first setup steps did not mention it. I noticed it in the directory listing and created the file.
- **Running Python code in PowerShell:** the first instructions for creating `check_h02.py` were unclear, and I pasted Python code directly into the PowerShell prompt instead of saving it in a file and running it with `python`.

These situations reminded me that AI-generated commands and instructions need to be checked against the actual development environment before using them.

## In my own words

**1. Why does a transfer to someone else's account return 404 and not 403?**

Returning 404 instead of 403 protects customers' privacy and account information. A 403 would tell the caller that the account exists but that they are not allowed to use it. Someone trying random account IDs could use this to discover valid accounts. A 404 gives the same answer whether the account is missing or belongs to another customer, so nothing is leaked.

**2. What would happen to a customer if the idempotency record were written in a separate transaction after the transfer?**

If the transfer is committed but the application crashes (or the network drops) before the idempotency record is saved, the customer never receives a response and will retry the same request with the same key. Because the record was never saved, the API would not recognize the request as a duplicate and would move the money a second time. The customer would be charged twice. Writing the transfer and the idempotency record in the same database transaction prevents this, because either both are saved or neither is.