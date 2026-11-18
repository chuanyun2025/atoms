"""Classify actionable build failures and keep retry identity independent of line numbers."""

import re

from atoms.gateway.provider_contract import ModelError

REPAIR_POLICIES = {
    "artifact": ("修复产物格式", "修复 JSON 格式、缺失字段或文件契约。保留已生成的有效源码，返回完整产物。"),
    "compile": ("修复编译错误", "从文件、行号和编译器报错定位语法、导入或导出问题，修正相关源码。"),
    "sandbox": ("修复沙箱兼容问题", "沿调用对象和事件来源修复确认违规的浏览器能力或 SDK 调用，保留正常的本地接口。"),
    "startup": ("修复预览启动错误", "根据运行异常追踪入口、初始化顺序和相关数据，修复启动路径。"),
    "validation": ("修复预览检查错误", "依据校验诊断定位变更范围，保留正常功能。"),
}
OUTPUT_STRATEGIES = {
    "MODEL_TRUNCATED": "减少可选样式和长内嵌素材，保留用户明确要求的功能，返回完整产物。",
    "ARTIFACT_LIMIT": "缩减内嵌素材或重复代码，保留核心功能与完整产物结构。",
    "ARTIFACT_REQUIREMENT": "按原始需求和项目规划修正实现方式，保留用户要求的功能。",
}
MODEL_OUTPUT_ERRORS = frozenset({"MODEL_EMPTY", "MODEL_TRUNCATED", "MODEL_PROTOCOL"})
VALIDATOR_CODES = frozenset(
    {
        "ARTIFACT_SCHEMA_INVALID",
        "ARTIFACT_LIMIT",
        "COMPILE_ERROR",
        "COMPILE_IMPORT",
        "SANDBOX_FORM_SUBMIT",
        "SANDBOX_NATIVE_STORAGE",
        "SANDBOX_SDK_SYNC",
        "SANDBOX_HTML_POLICY",
        "SANDBOX_CSS_POLICY",
        "PREVIEW_RUNTIME_ERROR",
        "PREVIEW_STARTUP_TIMEOUT",
    }
)
MAX_REPAIRS_PER_ISSUE = 2


def _root_text(value):
    value = re.sub(r"(?:^|\s)\(\d+:\d+\)", " ", value)
    value = re.sub(r":\d+:\d+(?=\s|$)", " ", value)
    value = re.sub(r"\b(line|column|col|char|position)\s+\d+", r"\1", value, flags=re.I)
    return " ".join(value.split())[:360]


class BuildIssue(ValueError):
    def __init__(self, code, message, *, file=None, line=None, column=None, subject=None, occurrences=None):
        super().__init__(message[:2000])
        self.code = code
        self.file = file
        self.line = line
        self.column = column
        self.subject = subject
        self.occurrences = occurrences
        self.category = {
            "ARTIFACT": "artifact",
            "MODEL": "artifact",
            "COMPILE": "compile",
            "SANDBOX": "sandbox",
            "PREVIEW": "startup",
        }.get(code.partition("_")[0], "validation")

    @classmethod
    def from_validator(cls, payload):
        message = payload.get("error")
        if not isinstance(message, str) or not message:
            message = "产物未通过检查"
        detail = payload.get("diagnostic")
        code = detail.get("code") if isinstance(detail, dict) else None
        if not isinstance(code, str) or code not in VALIDATOR_CODES:
            return cls("VALIDATION_FAILED", message)

        def short(name):
            value = detail.get(name)
            return value[:400] if isinstance(value, str) else None

        def coordinate(name):
            value = detail.get(name)
            return value if type(value) is int and value > 0 else None

        return cls(
            code,
            message,
            file=short("file"),
            line=coordinate("line"),
            column=coordinate("column"),
            subject=short("subject"),
            occurrences=coordinate("occurrences"),
        )

    @property
    def identity(self):
        return self.code, self.file, _root_text(self.subject or str(self)), self.occurrences or 1

    def report(self):
        fields = {
            "code": self.code,
            "category": self.category,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "subject": self.subject,
            "occurrences": self.occurrences,
        }
        return {key: value for key, value in fields.items() if value is not None}

    def repair(self, raw, failures, *, remaining):
        count = failures.get(self.identity, 0) + 1
        failures[self.identity] = count
        if count > MAX_REPAIRS_PER_ISSUE:
            raise ModelError(self.code, f"同一问题尝试修复 {MAX_REPAIRS_PER_ISSUE} 次后仍未通过。{str(self)[:1000]}")
        if not remaining:
            raise ModelError(self.code, str(self)[:1000])
        strategy = OUTPUT_STRATEGIES.get(self.code) or REPAIR_POLICIES[self.category][1]
        if count > 1:
            strategy += " 同一问题再次出现。根据本次诊断换一种解决路径，并复查具体失败位置。"
        return {
            "candidate": raw,
            "diagnostics": str(self),
            "diagnostic": self.report(),
            "repeated_failure": count > 1,
            "repair_strategy": strategy,
        }
