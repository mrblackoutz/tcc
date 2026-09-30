# SPDX-License-Identifier: LGPL-3.0-or-later
{
    "name": "TCC Accounts Payable Security Executor",
    "version": "19.0.0.1.0",
    "summary": "Restricted preflight boundary; financial effects remain disabled",
    "author": "Equipe TCC",
    "license": "LGPL-3",
    "depends": ["base", "rpc", "account", "purchase"],
    "data": ["security/executor_security.xml"],
    "application": False,
    "auto_install": False,
    "installable": True,
}
