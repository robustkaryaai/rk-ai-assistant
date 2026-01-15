#!/usr/bin/env python3
"""
Standalone test for self_diagnosis.py
Run this script to test the self-diagnosis system independently.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_self_diagnosis():
    """Test self-diagnosis system with simulated errors"""
    
    print("="*60)
    print("SELF-DIAGNOSIS STANDALONE TEST")
    print("="*60)
    
    # Import modules
    from rk_assistant.error_monitor import register_error, get_monitor
    from rk_assistant.self_diagnosis import SelfDiagnosis
    from rk_assistant.config import SLUG_FILE, GEMINI_API_KEY
    
    # Check prerequisites
    print("\n[1/6] Checking prerequisites...")
    if not GEMINI_API_KEY:
        print("❌ ERROR: GEMINI_API_KEY not set in .env file")
        print("   Please add GEMINI_API_KEY=your_key_here to .env")
        return False
    print("✓ GEMINI_API_KEY found")
    
    # Get slug
    print("\n[2/6] Getting device slug...")
    slug_path = Path(SLUG_FILE)
    if not slug_path.exists():
        print("⚠️  No slug file found, using test slug: 000000000")
        slug = "000000000"
    else:
        slug = slug_path.read_text().strip().split('\n')[0]
        print(f"✓ Using slug: {slug}")
    
    # Simulate some errors
    print("\n[3/6] Simulating errors...")
    register_error(
        error_type="test_import_error",
        message="ModuleNotFoundError: No module named 'fake_module'",
        severity="major",
        file_path="rk_assistant/test_module.py",
        line_number=15,
        traceback="Traceback (simulated)"
    )
    register_error(
        error_type="test_syntax_error",
        message="SyntaxError: invalid syntax",
        severity="critical",
        file_path="rk_assistant/test_file.py",
        line_number=42,
        traceback="Traceback (simulated)"
    )
    register_error(
        error_type="test_connection_error",
        message="Backend connection failed",
        severity="major",
        file_path="rk_assistant/command_poller.py",
        line_number=120
    )
    print("✓ 3 simulated errors registered")
    
    # Generate diagnostic report
    print("\n[4/6] Generating diagnostic report...")
    diag = SelfDiagnosis()
    report = diag.generate_diagnostic_report()
    print(f"✓ Report generated:")
    print(f"  - Total errors: {report['error_context']['total_errors']}")
    print(f"  - Files affected: {len(report['files_info'])}")
    print(f"  - System online: {report['system_info']['online']}")
    
    # Ask Gemini for error analysis
    print("\n[5/6] Asking Gemini to analyze errors...")
    print("  (This will make an API call to Gemini)")
    
    try:
        error_analysis = diag.ask_gemini_for_errors(report)
        
        if error_analysis:
            problematic_files = error_analysis.get('problematic_files', [])
            print(f"✓ Gemini identified {len(problematic_files)} problematic files:")
            for file_info in problematic_files:
                print(f"  - {file_info.get('file_path')}")
                print(f"    Error: {file_info.get('error_description')[:80]}...")
                print(f"    Severity: {file_info.get('severity')}")
        else:
            print("❌ Failed to get error analysis from Gemini")
            return False
    except Exception as e:
        print(f"❌ Error calling Gemini: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Summary
    print("\n[6/6] Test Summary:")
    print("✓ Error monitoring: WORKING")
    print("✓ Diagnostic report generation: WORKING")
    print("✓ Gemini integration: WORKING")
    
    print("\n" + "="*60)
    print("✅ SELF-DIAGNOSIS TEST COMPLETED SUCCESSFULLY")
    print("="*60)
    
    print("\nTo run full diagnosis with code fixing:")
    print("  result = diag.run_full_diagnosis(slug)")
    print("\nNote: Full diagnosis will:")
    print("  1. Analyze errors with Gemini")
    print("  2. Generate code fixes")
    print("  3. Test fixes in sandbox")
    print("  4. Apply fixes locally")
    print("  5. Report to backend")
    
    return True


if __name__ == "__main__":
    try:
        success = test_self_diagnosis()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
