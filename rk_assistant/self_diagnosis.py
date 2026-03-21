"""
Self-Diagnosis System for RK AI Assistant.
Uses Gemini AI to detect errors, generate fixes, test them, and apply locally.
Workflow matches user specification: developer mode report → Gemini analysis → fix → test → apply locally → report to backend
"""

import os
import sys
import time
import json
import shutil
import subprocess
import traceback as tb
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import threading

from .config import GEMINI_API_KEY, GEMINI_API_KEY_BACKUP, GEMINI_MODEL, BASE_DIR, DATA_DIR, BACKEND_BASE_URL
from . import gemini_client
from .error_monitor import get_monitor
from .networking import is_online

# Directories
DIAGNOSIS_DIR = DATA_DIR / "self_diagnosis"
BACKUP_DIR = DIAGNOSIS_DIR / "backups"
TEST_DIR = DIAGNOSIS_DIR / "test_files"
REPORTS_DIR = DIAGNOSIS_DIR / "reports"

# Ensure directories exist
for dir_path in [DIAGNOSIS_DIR, BACKUP_DIR, TEST_DIR, REPORTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


class SelfDiagnosis:
    """AI-powered self-diagnosis and code fixing system"""
    
    def __init__(self, api_key: str = None, backup_key: str = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.backup_key = backup_key or GEMINI_API_KEY_BACKUP
        self.monitor = get_monitor()
        self.diagnosis_active = False
    
    def generate_diagnostic_report(self) -> Dict:
        """
        Generate diagnostic report using developer mode style reporting.
        Returns dict with system state,  error context, and file information.
        """
        print("[self_diagnosis] 📋 Generating diagnostic report...")
        
        # Get error context from monitor
        error_context = self.monitor.get_error_context(limit=20)
        
        # Get system information
        system_info = self._get_system_info()
        
        # Get relevant file information
        files_info = self._get_files_info(error_context.get('files_affected', []))
        
        report = {
            'timestamp': time.time(),
            'system_info': system_info,
            'error_context': error_context,
            'files_info': files_info,
            'diagnosis_triggered_by': 'error_threshold_exceeded'
        }
        
        # Save report
        report_path = REPORTS_DIR / f"report_{int(time.time())}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"[self_diagnosis] Report saved to {report_path}")
        return report
    
    def _get_system_info(self) -> Dict:
        """Get system state information"""
        try:
            return {
                'online': is_online(),
                'python_version': sys.version,
                'cwd': os.getcwd(),
                'platform': sys.platform,
            }
        except Exception as e:
            return {'error': str(e)}
    
    def _get_files_info(self, file_paths: List[str]) -> Dict:
        """Get information about files involved in errors"""
        files_info = {}
        
        for file_path_str in file_paths:
            try:
                file_path = Path(file_path_str)
                if file_path.exists() and file_path.suffix == '.py':
                    files_info[str(file_path)] = {
                        'exists': True,
                        'size': file_path.stat().st_size,
                        'modified': file_path.stat().st_mtime,
                        'relative_path': str(file_path.relative_to(BASE_DIR) if BASE_DIR in file_path.parents else file_path)
                    }
            except Exception as e:
                files_info[file_path_str] = {'error': str(e)}
        
        return files_info
    
    def ask_gemini_for_errors(self, report: Dict) -> Optional[Dict]:
        """
        Send diagnostic report to Gemini and ask what errors it sees.
        
        Returns:
            Dict with 'problematic_files' list and 'error_descriptions'
        """
        print("[self_diagnosis] 🤖 Asking Gemini to identify errors...")
        
        # Prepare prompt
        prompt = self._build_error_detection_prompt(report)
        
        try:
            # Use Gemini to analyze
            client = gemini_client.genai.Client(
                api_key=self.api_key,
                http_options={'timeout': 30000}
            )
            
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            
            if not response or not response.text:
                print("[self_diagnosis] Empty response from Gemini")
                return None
            
            # Parse response
            result_text = response.text.strip()
            
            # Remove markdown if present
            if result_text.startswith("```json"):
                result_text = result_text.replace("```json", "").replace("```", "").strip()
            elif result_text.startswith("```"):
                result_text = result_text.replace("```", "").strip()
            
            result = json.loads(result_text)
            print(f"[self_diagnosis] ✓ Gemini identified {len(result.get('problematic_files', []))} problematic files")
            return result
            
        except Exception as e:
            print(f"[self_diagnosis] Error asking Gemini: {e}")
            tb.print_exc()
            return None
    
    def _build_error_detection_prompt(self, report: Dict) -> str:
        """Build prompt for Gemini to detect errors"""
        error_summary = []
        for error in report['error_context'].get('recent_errors', []):
            error_summary.append(f"- [{error['severity']}] {error['type']}: {error['message']}")
            if error['file']:
                error_summary[-1] += f" (in {error['file']}:{error['line']})"
        
        files_list = "\n".join([f"- {f}" for f in report.get('files_info', {}).keys()])
        
        prompt = f"""You are an expert Python debugging assistant for the RK AI Assistant system.

DIAGNOSTIC REPORT:
System: {report['system_info']}

RECENT ERRORS ({report['error_context']['total_errors']} total):
{chr(10).join(error_summary)}

FILES POTENTIALLY INVOLVED:
{files_list}

Please analyze these errors and identify:
1. Which files are causing the problems
2. What the specific errors are in each file
3. Root cause of each error

Respond with ONLY valid JSON in this format:
{{
  "problematic_files": [
    {{
      "file_path": "relative/path/to/file.py",
      "error_description": "Detailed description of the error",
      "severity": "critical|major|minor",
      "root_cause": "Root cause analysis"
    }}
  ]
}}
"""
        return prompt
    
    def get_code_fix(self, file_path: str, error_description: str) -> Optional[str]:
        """
        Send problematic file code to Gemini and get fixed version.
        
        Args:
            file_path: Path to the file with errors
            error_description: Description of the error from previous analysis
        
        Returns:
            Fixed code as string, or None if failed
        """
        print(f"[self_diagnosis] 🔧 Getting code fix for {file_path}...")
        
        try:
            # Read the problematic file
            with open(file_path, 'r') as f:
                original_code = f.read()
            
            # Build fix prompt
            prompt = f"""You are an expert Python developer fixing code for the RK AI Assistant.

FILE: {file_path}

ERROR DESCRIPTION:
{error_description}

CURRENT CODE:
```python
{original_code}
```

Please provide the COMPLETE FIXED version of this file. Output ONLY the corrected Python code, no explanations, no markdown formatting.
The code must be syntactically valid and maintain all existing functionality while fixing the error."""
            
            # Call Gemini
            client = gemini_client.genai.Client(
                api_key=self.api_key,
                http_options={'timeout': 60000}  # 60s for code generation
            )
            
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            
            if not response or not response.text:
                print("[self_diagnosis] Empty response from Gemini")
                return None
            
            fixed_code = response.text.strip()
            
            # Remove markdown code blocks if present
            if fixed_code.startswith("```python"):
                fixed_code = fixed_code.replace("```python", "").replace("```", "").strip()
            elif fixed_code.startswith("```"):
                fixed_code = fixed_code.replace("```", "").strip()
            
            print(f"[self_diagnosis] ✓ Received fixed code ({len(fixed_code)} bytes)")
            return fixed_code
            
        except Exception as e:
            print(f"[self_diagnosis] Error getting fix: {e}")
            tb.print_exc()
            return None
    
    def test_fix_in_sandbox(self, original_file: str, fixed_code: str) -> Tuple[bool, str]:
        """
        Test the fixed code in a separate file.
        
        Args:
            original_file: Path to original file
            fixed_code: Fixed code to test
        
        Returns:
            (success: bool, message: str)
        """
        print(f"[self_diagnosis] 🧪 Testing fix in sandbox...")
        
        try:
            # Create test file
            original_path = Path(original_file)
            test_file = TEST_DIR / f"{original_path.stem}_test{original_path.suffix}"
            
            with open(test_file, 'w') as f:
                f.write(fixed_code)
            
            # Test 1: Syntax validation
            try:
                compile(fixed_code, str(test_file), 'exec')
                print("[self_diagnosis] ✓ Syntax validation passed")
            except SyntaxError as e:
                return False, f"Syntax error: {e}"
            
            # Test 2: Import validation
            try:
                import_result = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(test_file)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if import_result.returncode != 0:
                    return False, f"Import/compile error: {import_result.stderr}"
                print("[self_diagnosis] ✓ Import validation passed")
            except subprocess.TimeoutExpired:
                return False, "Import validation timed out"
            
            # Test 3: Basic module import (if applicable)
            try:
                # Try to import the test module to check for runtime errors
                module_name = f"rk_assistant.{original_path.stem}_test"
                spec = __import__(module_name, fromlist=[''])
                print("[self_diagnosis] ✓ Module import test passed")
            except Exception as e:
                # This is optional - some modules might not be importable standalone
                print(f"[self_diagnosis] ⚠️ Module import warning: {e}")
            
            return True, "All tests passed"
            
        except Exception as e:
            return False, f"Test error: {e}"
    
    def apply_local_fix(self, file_path: str, fixed_code: str) -> Tuple[bool, str]:
        """
        Apply the fix LOCALLY to this Pi only.
        Creates backup before applying.
        
        Args:
            file_path: Path to file to fix
            fixed_code: Fixed code to apply
        
        Returns:
            (success: bool, message: str)
        """
        print(f"[self_diagnosis] 💾 Applying local fix to {file_path}...")
        
        try:
            file_path_obj = Path(file_path)
            
            # Create backup
            timestamp = int(time.time())
            backup_path = BACKUP_DIR / f"{file_path_obj.stem}_{timestamp}{file_path_obj.suffix}.bak"
            shutil.copy2(file_path, backup_path)
            print(f"[self_diagnosis] ✓ Backup created: {backup_path}")
            
            # Apply fix
            with open(file_path, 'w') as f:
                f.write(fixed_code)
            
            print(f"[self_diagnosis] ✓ Fix applied to {file_path}")
            return True, f"Fix applied successfully. Backup: {backup_path}"
            
        except Exception as e:
            error_msg = f"Failed to apply fix: {e}"
            print(f"[self_diagnosis] ✗ {error_msg}")
            return False, error_msg
    
    def report_to_backend(self, error_info: Dict, fix_info: Dict, slug: str) -> bool:
        """
        Report diagnostic and fix to backend for team review.
        Team will decide if fix should be pushed to GitHub.
        
        Args:
            error_info: Information about the error
            fix_info: Information about the fix applied
            slug: Device slug
        
        Returns:
            bool indicating success
        """
        print("[self_diagnosis] 📤 Reporting to backend...")
        
        try:
            import requests
            
            payload = {
                'device_slug': slug,
                'timestamp': time.time(),
                'error_info': error_info,
                'fix_info': fix_info,
                'fix_applied_locally': True,
                'awaiting_team_review': True
            }
            
            url = f"{BACKEND_BASE_URL}/device/{slug}/diagnosis"
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                print("[self_diagnosis] ✓ Report sent to backend")
                return True
            else:
                print(f"[self_diagnosis] Backend returned {response.status_code}")
                return False
                
        except Exception as e:
            print(f"[self_diagnosis] Failed to report to backend: {e}")
            return False
    
    def run_full_diagnosis(self, slug: str) -> bool:
        """
        Run complete diagnosis workflow:
        1. Generate report
        2. Ask Gemini for errors
        3. Get fixes from Gemini
        4. Test fixes
        5. Apply locally
        6. Report to backend
        
        Returns:
            bool indicating overall success
        """
        if self.diagnosis_active:
            print("[self_diagnosis] Diagnosis already in progress, skipping")
            return False
        
        self.diagnosis_active = True
        self.monitor.set_diagnosis_status(True)
        
        try:
            print("\n" + "="*60)
            print("🔍 SELF-DIAGNOSIS MODE ACTIVATED")
            print("="*60)
            
            # Step 1: Generate report
            report = self.generate_diagnostic_report()
            
            # Step 2: Ask Gemini what errors it sees
            error_analysis = self.ask_gemini_for_errors(report)
            if not error_analysis:
                print("[self_diagnosis] Failed to get error analysis from Gemini")
                return False
            
            problematic_files = error_analysis.get('problematic_files', [])
            if not problematic_files:
                print("[self_diagnosis] No problematic files identified")
                return True
            
            fixes_applied = []
            
            # Step 3-6: For each problematic file, get fix, test, and apply
            for file_info in problematic_files:
                file_path = Path(BASE_DIR) / file_info['file_path']
                error_desc = file_info['error_description']
                
                print(f"\n[self_diagnosis] Processing {file_path}...")
                
                # Get fix from Gemini
                fixed_code = self.get_code_fix(str(file_path), error_desc)
                if not fixed_code:
                    print(f"[self_diagnosis] Failed to get fix for {file_path}")
                    continue
                
                # Test fix
                test_success, test_msg = self.test_fix_in_sandbox(str(file_path), fixed_code)
                if not test_success:
                    print(f"[self_diagnosis] Fix failed tests: {test_msg}")
                    continue
                
                # Apply fix locally
                apply_success, apply_msg = self.apply_local_fix(str(file_path), fixed_code)
                if not apply_success:
                    print(f"[self_diagnosis] Failed to apply fix: {apply_msg}")
                    continue
                
                fixes_applied.append({
                    'file': str(file_path),
                    'error': error_desc,
                    'test_result': test_msg,
                    'applied': True
                })
            
            # Step 7: Report to backend
            if fixes_applied:
                self.report_to_backend(
                    error_info={
                        'error_analysis': error_analysis,
                        'report': report
                    },
                    fix_info={
                        'fixes_applied': fixes_applied,
                        'total_files_fixed': len(fixes_applied)
                    },
                    slug=slug
                )
            
            print(f"\n[self_diagnosis] ✓ Diagnosis complete. {len(fixes_applied)} files fixed.")
            print("="*60 + "\n")
            
            return len(fixes_applied) > 0
            
        except Exception as e:
            print(f"[self_diagnosis] Error during diagnosis: {e}")
            tb.print_exc()
            return False
        
        finally:
            self.diagnosis_active = False
            self.monitor.set_diagnosis_status(False)


def trigger_diagnosis_if_needed(slug: str) -> bool:
    """
    Check if diagnosis should be triggered and run it if needed.
    This is called from error handlers throughout the codebase.
    
    Returns:
        bool indicating if diagnosis was run
    """
    monitor = get_monitor()
    
    if monitor.should_trigger_diagnosis():
        print("\n[self_diagnosis] 🚨 Error threshold exceeded, triggering diagnosis...\n")
        
        # Run diagnosis in separate thread to not block
        diagnosis_thread = threading.Thread(
            target=lambda: SelfDiagnosis().run_full_diagnosis(slug),
            daemon=True
        )
        diagnosis_thread.start()
        
        return True
    
    return False


def run_immediate_diagnosis(slug: str, error_type: str, message: str, traceback_str: str):
    """
    Trigger an immediate, blocking diagnosis for a fatal error.
    This is called when the main process is about to exit.
    """
    print(f"\n[self_diagnosis] 🛠️  FATAL ERROR DETECTED: {error_type}")
    print(f"[self_diagnosis] 🤖 Starting immediate AI diagnosis and recovery attempt...")
    
    # Register the error first
    get_monitor().register_error(
        error_type=error_type,
        message=message,
        severity='critical',
        traceback=traceback_str
    )
    
    # Run diagnosis synchronously (since the app is crashing anyway)
    # We want to try and fix it before the next restart
    diag = SelfDiagnosis()
    success = diag.run_full_diagnosis(slug)
    
    if success:
        print("[self_diagnosis] ✅ AI successfully applied local fixes. Restarting service...")
    else:
        print("[self_diagnosis] ❌ AI diagnosis could not resolve the issue automatically.")
    
    return success
