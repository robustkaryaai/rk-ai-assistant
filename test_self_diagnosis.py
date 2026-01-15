#!/usr/bin/env python3
"""
Test script for self-diagnosis system.
Run this to simulate errors and trigger diagnosis.
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from rk_assistant.error_monitor import register_error, get_monitor
from rk_assistant import self_diagnosis
from rk_assistant.config import SLUG_FILE

def test_error_monitoring():
    """Test error monitoring and threshold detection"""
    print("="*60)
    print("TEST 1: Error Monitoring")
    print("="*60)
    
    monitor = get_monitor()
    
    # Simulate minor errors
    print("\n[1/4] Registering 5 minor errors...")
    for i in range(5):
        should_diagnose = register_error(
            error_type="test_minor_error",
            message=f"Test minor error #{i+1}",
            severity="minor",
            file_path=__file__
        )
        print(f"  Error {i+1} registered. Diagnosis triggered: {should_diagnose}")
        time.sleep(0.1)
    
    # Simulate major error
    print("\n[2/4] Registering major errors (threshold: 3)...")
    for i in range(3):
        should_diagnose = register_error(
            error_type="test_major_error",
            message=f"Test major error #{i+1}",
            severity="major",
            file_path=__file__,
            traceback="Traceback (simulated)..."
        )
        print(f"  Major error {i+1} registered. Diagnosis triggered: {should_diagnose}")
        time.sleep(0.1)
    
    # Check error context
    print("\n[3/4] Getting error context...")
    context = monitor.get_error_context(limit=10)
    print(f"  Total errors: {context['total_errors']}")
    print(f"  Error types: {context['error_types']}")
    print(f"  Severity dist: {context['severity_distribution']}")
    
    # Clear old errors
    print("\n[4/4] Clearing old errors...")
    monitor.clear_old_errors(older_than_seconds=0)
    print("  ✓ Errors cleared")
    
    print("\n✓ Error monitoring test complete\n")


def test_diagnostic_report():
    """Test diagnostic report generation"""
    print("="*60)
    print("TEST 2: Diagnostic Report Generation")
    print("="*60)
    
    # First add some test errors
    print("\n[1/2] Adding test errors...")
    for i in range(3):
        register_error(
            error_type="backend_error",
            message=f"Backend connection failed {i+1}",
            severity="major",
            file_path="rk_assistant/command_poller.py",
            line_number=120 + i
        )
    
    # Generate report
    print("\n[2/2] Generating diagnostic report...")
    diag = self_diagnosis.SelfDiagnosis()
    report = diag.generate_diagnostic_report()
    
    print(f"  ✓ Report generated:")
    print(f"    - Total errors: {report['error_context']['total_errors']}")
    print(f"    - Files affected: {len(report['files_info'])}")
    print(f"    - System online: {report['system_info']['online']}")
    
    print("\n✓ Diagnostic report test complete\n")


def test_full_diagnosis_dry_run():
    """Test full diagnosis workflow (dry run - no actual fixes applied)"""
    print("="*60)
    print("TEST 3: Full Diagnosis Workflow (Dry Run)")
    print("="*60)
    
    # Read slug
    slug_path = Path(SLUG_FILE)
    if not slug_path.exists():
        print("⚠️  No slug file found, using test slug")
        slug = "000000000"
    else:
        slug = slug_path.read_text().strip().split('\n')[0]
    
    print(f"\nUsing device slug: {slug}")
    print("\nNote: This is a DRY RUN. No actual fixes will be applied.")
    print("      It will test report generation and Gemini integration.\n")
    
    # Add test errors
    print("[1/3] Simulating errors...")
    register_error(
        error_type="import_error",
        message="ModuleNotFoundError: No module named 'test_module'",
        severity="critical",
        file_path="rk_assistant/test_file.py",
        line_number=10,
        traceback="Traceback (most recent call last):\n  File test_file.py, line 10\nModuleNotFoundError"
    )
    
    print("\n[2/3] Generating diagnostic report...")
    diag = self_diagnosis.SelfDiagnosis()
    report = diag.generate_diagnostic_report()
    print(f"  ✓ Report generated with {report['error_context']['total_errors']} errors")
    
    print("\n[3/3] Testing Gemini error detection...")
    print("  Note: This requires GEMINI_API_KEY to be set")
    print("  Skipping Gemini call in dry run mode")
    
    # In a real test, you would call:
    # error_analysis = diag.ask_gemini_for_errors(report)
    
    print("\n✓ Full diagnosis dry run complete\n")


def run_all_tests():
    """Run all tests"""
    try:
        test_error_monitoring()
        test_diagnostic_report()
        test_full_diagnosis_dry_run()
        
        print("="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\nTo test on the Pi:")
        print("1. Copy files to Pi")
        print("2. Restart service: sudo systemctl restart rk-assistant.service")
        print("3. Monitor logs: sudo journalctl -u rk-assistant.service -f")
        print("4. Simulate errors to trigger diagnosis")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
