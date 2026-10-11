"""Local Laya decision model for qualifying DK-Tech lead posts."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from laya_adapter import configured_model_version

os.environ.setdefault("USE_TF", "0")

MODEL = "convaiinnovations/laya/multilingual"
CLASSIFIER_VERSION = "2026-10-11-trained-post-type-v3-" + configured_model_version()
MIN_CONFIDENCE = 0.60
UNCERTAIN_POST_TYPE_SEND_THRESHOLD = 0.70

QUESTIONS = {
    "intent": {
        "type": "choice",
        "instructions": (
            "Does the author currently want an outside provider, quote, or help to deliver a project? "
            "Classify the author's role and requested action, not just keywords such as website, tuyển dụng, or inbox."
        ),
        "criteria": {
            "seeking_provider": (
                "The author is a potential client asking an outside person/company to do work for them or asking for a quote. "
                "Vietnamese cues include 'mình cần làm website', 'tìm đơn vị làm app', 'bên nào nhận code', 'xin báo giá', "
                "'ai nhận dự án này'. The author wants to BUY or commission a service."
            ),
            "not_seeking_provider": (
                "The author is not looking to buy an outside service. This includes (1) recruitment/job vacancies where "
                "the author or their company hires an employee, intern, or freelancer to join their own team, and (2) "
                "self-promotion where the author offers their own services, agency, product, or portfolio to attract clients. "
                "Also includes discussion, completed work, and unrelated posts. 'Tuyển lập trình viên, gửi CV', "
                "'bên mình đang tuyển', 'nhận thiết kế website', 'agency mình vừa làm dự án', and 'inbox để sử dụng dịch vụ' "
                "are not requests for DK-Tech to provide a service."
            ),
        },
    },
    "post_type": {
        "type": "choice",
        "instructions": (
            "Identify the post's primary purpose. Distinguish a client seeking an outside vendor from an employer recruiting "
            "staff and from an author advertising their own offering. Use other only when none is the main purpose."
        ),
        "criteria": {
            "service_request": (
                "The author needs an outside provider to build, fix, or quote a project for them. They are the buyer/client. "
                "Examples: 'Cần tìm bên làm website bán hàng', 'ai nhận làm app quản lý kho?', 'xin báo giá phần mềm CRM'."
            ),
            "recruitment": (
                "The author or their organization is hiring a person to join a team or fill a job. Look for role/title, "
                "salary, qualifications, work location, application instructions, or CV/contact details. Examples: "
                "'Công ty mình tuyển nhân viên IT', 'tuyển intern frontend, gửi CV', 'cần tuyển dev full-time'. "
                "A company seeking an employee is not a client seeking DK-Tech as a vendor."
            ),
            "self_promotion": (
                "The author is promoting or selling their own services, company, product, or completed work to attract clients. "
                "Look for claims about what 'mình/bên mình/công ty mình' offers, portfolio/case studies, price/package, "
                "or a call to inbox/order. Examples: 'Nhận thiết kế website trọn gói', 'agency bên mình vừa ra mắt app', "
                "'inbox để được tư vấn dịch vụ'. The author is the seller, not a buyer looking for a provider."
            ),
            "other": (
                "Discussion, question, news, completed-work share without a service offer, or another post that is neither "
                "a service request, recruitment, nor self-promotion."
            ),
        },
    },
    "service": {
        "type": "choice",
        "instructions": "Which service category best matches the concrete need described in the post?",
        "criteria": {
            "website": "Website, landing page, online store, or web design/development.",
            "software": "Custom software, business application, CRM, ERP, or an internal management system.",
            "automation": "A bot, automation, API integration, crawler, or workflow automation.",
            "other": "No clear need in the supported categories above.",
        },
    },
    "safety": {
        "type": "choice",
        "instructions": "Is the requested service safe for DK-Tech to offer?",
        "criteria": {
            "A": "Safe: ordinary website, software, app, or business automation work, with no gambling, fraud, or other harmful purpose.",
            "B": "Unsafe or unclear: gambling, betting, casino, fraud, illegal activity, or a harmful/ambiguous purpose.",
        },
    },
}

_agent = None
_post_type_adapter = None
_load_error: str | None = None
_lock = threading.Lock()
_predict_lock = threading.Lock()


def _get_agent():
    global _agent, _post_type_adapter, _load_error
    if _agent is not None:
        return _agent
    with _lock:
        if _agent is None:
            try:
                import laya
                from huggingface_hub import snapshot_download

                model_source = "convaiinnovations/laya"
                required = (
                    "model.safetensors", "rl_agent_config.json", "encoder/config.json",
                    "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json",
                )
                try:
                    cached = Path(snapshot_download(
                        model_source, local_files_only=True,
                        allow_patterns=[f"multilingual/{name}" for name in required],
                    ))
                    if all((cached / "multilingual" / name).is_file() for name in required):
                        model_source = str(cached)
                except FileNotFoundError:
                    pass
                agent = laya.load(model_source, subfolder="multilingual", device="cpu")
                from laya_adapter import load_adapter
                adapter = load_adapter(agent)
                _post_type_adapter = adapter
                _agent = agent
                _load_error = None
            except Exception as exc:
                _load_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(f"Không tải được model Laya multilingual: {_load_error}") from exc
    return _agent


def status() -> dict:
    try:
        import importlib.metadata

        version = importlib.metadata.version("laya")
        available = True
        error = None
    except Exception as exc:
        version = None
        available = False
        error = str(exc)
    return {
        "available": available,
        "loaded": _agent is not None,
        "model": MODEL,
        "version": version,
        "classifierVersion": CLASSIFIER_VERSION,
        "postTypeTraining": {
            "loaded": _post_type_adapter is not None,
            "version": _post_type_adapter.manifest["runVersion"] if _post_type_adapter else None,
            "method": "classifier_head_with_frozen_laya_encoder_and_tfidf" if _post_type_adapter else None,
        },
        "error": _load_error or error,
        "minimumConfidence": MIN_CONFIDENCE,
    }


def allows_uncertain_post_type(result: dict) -> bool:
    """Owner policy: a type prediction below 70% must not veto a supported, safe post."""
    confidences = result.get("confidences") or {}
    type_confidence = confidences.get("post_type")
    if type_confidence is None or result.get("postType") not in {
        "service_request", "recruitment", "self_promotion", "other"
    }:
        return False
    try:
        return (
            0 <= float(type_confidence) < UNCERTAIN_POST_TYPE_SEND_THRESHOLD
            and result.get("bucket") != "blocked"
            and result.get("service") in {"website", "software", "automation"}
            and result.get("safety") == "safe"
            and float(confidences.get("service", 0)) >= MIN_CONFIDENCE
            and float(confidences.get("safety", 0)) >= MIN_CONFIDENCE
        )
    except (TypeError, ValueError):
        return False


def classify(post_text: str) -> dict:
    text = (post_text or "").strip()
    if not text:
        raise ValueError("Bài không có nội dung để phân loại bằng Laya")
    agent = _get_agent()
    with _predict_lock:
        if _post_type_adapter is not None:
            result = agent.predict(text[:12000], {key: QUESTIONS[key] for key in ("service", "safety")},
                                   max_len=1024, head_max_len=256)
            answers = result.get("answers") or {}
            typed = _post_type_adapter.predict(agent, text[:12000])
            answers["post_type"] = typed
            request_probability = float((typed.get("probabilities") or {}).get("service_request", 0))
            is_request = typed.get("choice") == "service_request"
            answers["intent"] = {
                "choice": "seeking_provider" if is_request else "not_seeking_provider",
                "answer_confidence": request_probability if is_request else 1 - request_probability,
                "probabilities": {"seeking_provider": request_probability, "not_seeking_provider": 1-request_probability},
            }
        else:
            result = agent.predict(text[:12000], QUESTIONS, max_len=1024, head_max_len=256)
            answers = result.get("answers") or {}
    intent = answers.get("intent") or {}
    post_type = answers.get("post_type") or {}
    service = answers.get("service") or {}
    safety = answers.get("safety") or {}

    def answer_confidence(answer: dict) -> float:
        # Laya's `confidence` for choice questions is entropy-based; use its calibrated
        # probability for the selected answer when the installed version provides it.
        value = answer.get("answer_confidence", answer.get("confidence", 0))
        return float(value or 0)

    intent_label = str(intent.get("choice") or "").strip().lower()
    post_type_label = str(post_type.get("choice") or "").strip().lower()
    service_label = str(service.get("choice") or "").strip().lower()
    safety_label = str(safety.get("choice") or "").strip().upper()
    confidences = {
        "intent": answer_confidence(intent),
        "post_type": answer_confidence(post_type),
        "service": answer_confidence(service),
        "safety": answer_confidence(safety),
    }

    supported = service_label in {"website", "software", "automation"}
    unsafe = safety_label == "B" and confidences["safety"] >= MIN_CONFIDENCE
    confident = all(value >= MIN_CONFIDENCE for value in confidences.values())
    post_type_minimum = (_post_type_adapter.manifest.get("minimumPostTypeConfidence", MIN_CONFIDENCE)
                         if _post_type_adapter else MIN_CONFIDENCE)
    qualified = (intent_label == "seeking_provider" and post_type_label == "service_request"
                 and confidences["post_type"] >= post_type_minimum
                 and supported and safety_label == "A" and confident)
    qualified = qualified or allows_uncertain_post_type({
        "postType": post_type_label, "service": service_label,
        "safety": "safe" if safety_label == "A" else "unsafe",
        "confidences": confidences,
    })
    bucket = "blocked" if unsafe else "qualified" if qualified else "uncertain"
    labels = {
        "intent": intent_label or "unknown",
        "post_type": post_type_label or "unknown",
        "service": service_label or "unknown",
        "safety": "unsafe" if unsafe else "safe" if safety_label == "A" else "unknown",
    }
    return {
        "status": "done",
        "bucket": bucket,
        "label": labels["intent"],
        "confidence": min(confidences.values()),
        "service": labels["service"],
        "postType": labels["post_type"],
        "postTypeModel": "trained_head_on_laya_encoder" if _post_type_adapter else "zero_shot",
        "postTypeMinimumConfidence": post_type_minimum,
        "safety": labels["safety"],
        "labels": labels,
        "confidences": confidences,
        "probabilities": {
            key: answer.get("probabilities", {})
            for key, answer in (("intent", intent), ("post_type", post_type),
                                ("service", service), ("safety", safety))
        },
        "model": MODEL,
        "classifierVersion": CLASSIFIER_VERSION,
        "minimumConfidence": MIN_CONFIDENCE,
    }
