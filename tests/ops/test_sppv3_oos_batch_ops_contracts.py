"""단위 테스트 — SPPV-3 OOS 배치의 운영 정의(Compose 서비스, systemd
템플릿) 계약 검사. DB/네트워크 미사용, 파일만 파싱한다.

docs/40_action_plans/sppv3_oos_daily_batch_design_2026-08-25.md §4/§45가
정한 아키텍처(21:00 KST, 주문 scheduler와 분리된 one-shot, historical
daily bar만 호출)가 실제 파일(``docker-compose.yml``, ``ops/systemd/*``)에
그대로 반영됐는지 확인한다.
"""

from __future__ import annotations

import os
import re

import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_COMPOSE_PATH = os.path.join(_REPO_ROOT, "docker-compose.yml")
_SYSTEMD_DIR = os.path.join(_REPO_ROOT, "ops", "systemd")
_SERVICE_TEMPLATE_PATH = os.path.join(_SYSTEMD_DIR, "sppv3-oos-batch.service")
_TIMER_TEMPLATE_PATH = os.path.join(_SYSTEMD_DIR, "sppv3-oos-batch.timer")


def _load_compose() -> dict:
    with open(_COMPOSE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sppv3_service() -> dict:
    compose = _load_compose()
    return compose["services"]["sppv3-oos-batch"]


class TestComposeServiceIsolatedFromOpsScheduler:
    def test_service_exists_and_is_distinct_from_ops_scheduler(self):
        compose = _load_compose()
        assert "sppv3-oos-batch" in compose["services"]
        assert "ops-scheduler" in compose["services"]
        assert compose["services"]["sppv3-oos-batch"] is not compose["services"]["ops-scheduler"]

    def test_service_has_no_restart_policy(self):
        """one-shot 서비스는 long-lived 컨테이너처럼 자동 재시작하면 안 된다."""
        service = _sppv3_service()
        assert "restart" not in service

    def test_service_is_gated_behind_its_own_compose_profile(self):
        """profiles가 없으면 `docker compose up -d`가 무심코 이 서비스를 상시 기동시킬 수 있다."""
        service = _sppv3_service()
        assert service.get("profiles") == ["sppv3-oos-batch"]

    def test_command_invokes_the_wrapper_script_not_ops_scheduler(self):
        service = _sppv3_service()
        command = " ".join(str(c) for c in service["command"])
        assert "run_sppv3_oos_batch.py" in command
        assert "run_ops_scheduler.py" not in command


class TestComposeServiceEnvMinimality:
    _FORBIDDEN_ENV_KEYS = (
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_PASSWORD",
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "KIS_ACCOUNT_NO",
        "KIS_ACCOUNT_NUMBER",
        "KIS_ACCOUNT_PRODUCT_CODE",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "NAVER_CLIENT_SECRET",
    )

    def test_no_db_or_order_account_env_keys_declared(self):
        service = _sppv3_service()
        declared_keys = set(service.get("environment", {}).keys())
        overlap = declared_keys & set(self._FORBIDDEN_ENV_KEYS)
        assert not overlap, f"금지된 env 키가 배선됨: {overlap}"

    def test_kis_live_info_enabled_is_hardcoded_true(self):
        """076 국내휴장일조회로 거래일을 확정 판정하려면 항상 "true"로 고정
        배선해야 한다(§45.7 정정, §47.1) — 2026-08-25 초판의 "false 고정"은
        평일 공휴일을 걸러내지 못해 폐기됐다."""
        service = _sppv3_service()
        assert service["environment"]["KIS_LIVE_INFO_ENABLED"] == "true"

    def test_quote_client_credentials_are_wired(self):
        service = _sppv3_service()
        env = service["environment"]
        assert "KIS_LIVE_INFO_APP_KEY" in env
        assert "KIS_LIVE_INFO_APP_SECRET" in env

    def test_volumes_do_not_mount_env_file(self):
        service = _sppv3_service()
        volumes = " ".join(str(v) for v in service.get("volumes", []))
        assert ".env" not in volumes


class TestRuntimeEnvWiringContractCoversNewService:
    def test_contract_registers_sppv3_oos_batch_required_keys(self):
        import json

        contract_path = os.path.join(
            _REPO_ROOT, "scripts", "harness", "contracts", "runtime_env_wiring.json"
        )
        with open(contract_path, encoding="utf-8") as f:
            contract = json.load(f)
        entries_for_service = [
            e for e in contract["entries"] if "sppv3-oos-batch" in e.get("services", [])
        ]
        keys = {e["key"] for e in entries_for_service}
        assert {"KIS_LIVE_INFO_ENABLED", "KIS_LIVE_INFO_APP_KEY", "KIS_LIVE_INFO_APP_SECRET"} <= keys
        assert all(e["required_in_compose"] is True for e in entries_for_service)


class TestSystemdServiceTemplate:
    def _read_service(self) -> str:
        with open(_SERVICE_TEMPLATE_PATH, encoding="utf-8") as f:
            return f.read()

    def test_is_oneshot_type(self):
        assert "Type=oneshot" in self._read_service()

    def _execstart_line(self) -> str:
        content = self._read_service()
        match = re.search(r"^ExecStart=(.+)$", content, re.MULTILINE)
        assert match is not None, "ExecStart 라인을 찾지 못함"
        return match.group(0)

    def test_execstart_run_rm_not_exec(self):
        content = self._read_service()
        execstart = self._execstart_line()
        assert "run --rm sppv3-oos-batch" in execstart
        assert re.search(r"^ExecStart=.*docker exec", content, re.MULTILINE) is None

    def test_execstart_uses_docker_compose_env_wrapper_not_docker_compose_directly(self):
        """2026-08-26 정정 — 표준 배포 래퍼(docker_compose_env.sh)를 반드시
        경유해야 /etc/agent_trading/*.env가 Compose interpolation에
        전달된다. 이 래퍼 없이 `docker compose`를 직접 부르면 KIS
        live-info 자격증명이 빈 문자열로 치환된다."""
        execstart = self._execstart_line()
        assert "docker_compose_env.sh" in execstart
        assert "docker compose " not in execstart

    def test_execstart_passes_profile_flag(self):
        execstart = self._execstart_line()
        assert "--profile sppv3-oos-batch" in execstart

    def test_no_docker_compose_bin_placeholder_remains(self):
        """DOCKER_COMPOSE_BIN 자리표시자는 docker_compose_env.sh 경유
        전환으로 더 이상 필요 없어져 제거됐다 — ExecStart를 포함한 실제
        unit 지시문 라인에는 더 이상 등장하지 않아야 한다(정정 사유를
        설명하는 주석 문장 자체는 허용)."""
        content = self._read_service()
        directive_lines = [
            line
            for line in content.splitlines()
            if line and not line.lstrip().startswith("#") and "=" in line
        ]
        assert not any("__DOCKER_COMPOSE_BIN__" in line for line in directive_lines)

    def test_path_environment_is_explicitly_set(self):
        """systemd 최소 PATH에서 docker_compose_env.sh가 내부적으로
        찾는 `docker` 바이너리를 못 찾는 사고를 구조적으로 방지한다."""
        content = self._read_service()
        assert re.search(r"^Environment=PATH=.*:/usr/bin:", content, re.MULTILINE) is not None

    def test_does_not_reference_ops_scheduler_container(self):
        assert "agent_trading-ops-scheduler" not in self._read_service()

    def test_restart_is_disabled(self):
        assert "Restart=no" in self._read_service()

    def test_has_repo_root_placeholder_not_hardcoded_path(self):
        content = self._read_service()
        assert "__AGENT_TRADING_REPO_ROOT__" in content
        assert "/workspace/agent_trading_dev" not in content


class TestSystemdTimerTemplate:
    def _read_timer(self) -> str:
        with open(_TIMER_TEMPLATE_PATH, encoding="utf-8") as f:
            return f.read()

    def test_oncalendar_is_2100_kst_daily(self):
        content = self._read_timer()
        match = re.search(r"^OnCalendar=(.+)$", content, re.MULTILINE)
        assert match is not None
        oncalendar = match.group(1).strip()
        assert "Asia/Seoul" in oncalendar
        assert "21:00:00" in oncalendar

    def test_persistent_is_true(self):
        assert re.search(r"^Persistent=true$", self._read_timer(), re.MULTILINE) is not None


class TestInstallScriptDefaultsToDryRun:
    def _read_install_script(self) -> str:
        install_path = os.path.join(_SYSTEMD_DIR, "install_sppv3_oos_batch_systemd.sh")
        with open(install_path, encoding="utf-8") as f:
            return f.read()

    def test_apply_defaults_to_zero(self):
        content = self._read_install_script()
        assert 'APPLY=0' in content

    def test_daemon_reload_enable_start_are_gated_behind_apply_check(self):
        content = self._read_install_script()
        # 주석(#)이 아닌 실제 실행 라인만 검사한다 — docstring 주석에서
        # 이 명령들을 설명하는 문장은 정상적으로 등장해야 하므로 제외한다.
        code_lines = [
            line for line in content.splitlines() if not line.lstrip().startswith("#")
        ]
        code_text = "\n".join(code_lines)
        dry_run_exit_index = code_text.index("dry-run 종료")
        apply_section = code_text[dry_run_exit_index:]
        assert "systemctl daemon-reload" in apply_section
        assert "systemctl enable" in apply_section
        assert "systemctl start" in apply_section
        pre_dry_run_section = code_text[:dry_run_exit_index]
        assert "systemctl daemon-reload" not in pre_dry_run_section
        assert "systemctl enable" not in pre_dry_run_section
        assert "systemctl start" not in pre_dry_run_section

    def test_no_docker_compose_bin_variable_remains(self):
        """2026-08-26 정정 — ExecStart가 docker_compose_env.sh를 경유하도록
        바뀌면서 DOCKER_COMPOSE_BIN 변수/치환이 더 이상 필요 없어졌다 —
        실제 셸 코드(주석 아님)에서 변수로 쓰이지 않아야 한다."""
        content = self._read_install_script()
        code_lines = [
            line for line in content.splitlines() if not line.lstrip().startswith("#")
        ]
        assert not any("DOCKER_COMPOSE_BIN" in line for line in code_lines)

    def test_validates_rendered_execstart_uses_wrapper_before_apply(self):
        """설치 스크립트 자신이 렌더링 직후 ExecStart가 docker_compose_env.sh를
        경유하는지, docker compose를 직접 부르지 않는지 자체 검증해야 한다 —
        템플릿을 손으로 고치다 회귀시키는 사고를 설치 시점에 잡기 위함."""
        content = self._read_install_script()
        assert "docker_compose_env.sh" in content
        assert 'docker compose "* ]]' in content or "docker compose \"* ]]" in content


class TestInstallScriptDryRunRendersWrapperExecStart:
    """실제 설치 스크립트를 dry-run(--yes 없이) 서브프로세스로 실행해,
    렌더링된 unit의 ExecStart가 wrapper 경유인지 확인한다. `--yes`를
    붙이지 않으므로 daemon-reload/enable/start/파일 쓰기는 전혀
    일어나지 않는다 — DB/네트워크 미사용."""

    def test_dry_run_output_contains_wrapper_execstart_not_direct_docker_compose(self, tmp_path):
        import subprocess

        fake_repo = tmp_path / "fake_repo"
        (fake_repo / "scripts" / "harness").mkdir(parents=True)
        (fake_repo / "docker-compose.yml").write_text("services: {}\n")
        (fake_repo / "scripts" / "harness" / "docker_compose_env.sh").write_text("#!/usr/bin/env bash\n")

        install_script = os.path.join(_SYSTEMD_DIR, "install_sppv3_oos_batch_systemd.sh")
        result = subprocess.run(
            ["bash", install_script],
            env={**os.environ, "AGENT_TRADING_REPO_ROOT": str(fake_repo)},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "docker_compose_env.sh" in result.stdout
        assert "--profile sppv3-oos-batch run --rm sppv3-oos-batch" in result.stdout
        assert "dry-run 종료" in result.stdout
