import unittest
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent


class DeployContractTest(unittest.TestCase):
    def test_bootstrap_delegates_to_versioned_release(self):
        bootstrap = (API_ROOT / "deploy" / "deploy").read_text()

        self.assertIn('exec "$SOURCE_DIR/api/deploy/release" "$SHA"', bootstrap)

    def test_release_requires_and_starts_api_worker_and_sandbox(self):
        release = (API_ROOT / "deploy" / "release").read_text()

        self.assertIn("for required_service in backend worker sandbox", release)
        self.assertIn("up -d --build backend worker sandbox", release)
        self.assertIn('wait_healthy "$API_CONTAINER"', release)
        self.assertIn('wait_healthy "$WORKER_CONTAINER"', release)
        self.assertIn('wait_healthy "$SANDBOX_CONTAINER"', release)
        self.assertIn("python3 -m app.workspace_smoke", release)

    def test_workflow_refreshes_bootstrap_before_deploying(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "deploy-api.yml").read_text()

        upload = workflow.index("Upload deployment bootstrap")
        install = workflow.index("install -m 0755")
        deploy = workflow.index(
            "/opt/workspace/apps/aristotle-api/deploy ${{ github.sha }}"
        )
        self.assertLess(upload, install)
        self.assertLess(install, deploy)


if __name__ == "__main__":
    unittest.main()
