#!/usr/bin/env python3
"""
Test file with intentional error for self-diagnosis demo.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from rk_assistant.error_monitor import register_error
from rk_assistant.self_diagnosis import SelfDiagnosis
from rk_assistant.networking import read_slug

def create_intentional_error():
    """Create a test file with an intentional syntax/logic error"""
    
    # Create a simple test module with an error
    test_file_path = Path(__file__).parent / "rk_assistant" / "broken_test_module.py"
    
    broken_code = '''"""
Test module with intentional error for self-diagnosis demo.
This has a missing colon in the function definition.
"""

def calculate_sum(a, b)  # Missing colon here!
    return a + b

def main():
    result = calculate_sum(5, 10)
    print(f"Result: {result}")

if __name__ == "__main__":
    main()
'''
    
    # Write the broken code
    with open(test_file_path, 'w') as f:
        f.write(broken_code)
    
    print(f"✓ Created test file with intentional error: {test_file_path}")
    return test_file_path


def trigger_full_diagnosis():
    """Trigger full diagnosis workflow"""
    
    print("\n" + "="*60)
    print("FULL SELF-DIAGNOSIS DEMO")
    print("="*60)
    
    # Step 1: Create intentional error
    print("\n[1/5] Creating test file with intentional error...")
    test_file = create_intentional_error()
    
    # Step 2: Register the error
    print("\n[2/5] Registering error in monitoring system...")
    register_error(
        error_type="syntax_error",
        message=f"SyntaxError: invalid syntax in {test_file}",
        severity="critical",
        file_path=str(test_file),
        line_number=6,
        traceback="  File broken_test_module.py, line 6\n    def calculate_sum(a, b)\n                           ^\nSyntaxError: invalid syntax"
    )
    print("✓ Error registered (critical severity - will trigger diagnosis)")
    
    # Step 3: Get slug
    print("\n[3/5] Getting device slug...")
    slug, _ = read_slug()
    print(f"✓ Device slug: {slug}")
    
    # Step 4: Run full diagnosis
    print("\n[4/5] Running FULL diagnosis workflow...")
    print("This will:")
    print("  → Generate diagnostic report")
    print("  → Ask Gemini to identify errors")
    print("  → Get fixed code from Gemini")
    print("  → Test fix in sandbox")
    print("  → Apply fix locally (with backup)")
    print("  → Report to backend")
    print()
    
    diag = SelfDiagnosis()
    success = diag.run_full_diagnosis(slug)
    
    # Step 5: Verify the fix
    print("\n[5/5] Verifying fix was applied...")
    if test_file.exists():
        with open(test_file, 'r') as f:
            fixed_code = f.read()
        
        if 'def calculate_sum(a, b):' in fixed_code:
            print("✓ Fix verified! The missing colon has been added.")
            print(f"\nFixed code preview:")
            print("-" * 40)
            for i, line in enumerate(fixed_code.split('\n')[4:8], start=5):
                print(f"{i}: {line}")
            print("-" * 40)
        else:
            print("⚠️ Fix may not have been applied correctly")
    
    # Check for backup
    from rk_assistant.self_diagnosis import BACKUP_DIR
    backups = list(BACKUP_DIR.glob("broken_test_module_*.bak"))
    if backups:
        print(f"\n✓ Backup created: {backups[-1]}")
    
    print("\n" + "="*60)
    if success:
        print("✅ FULL DIAGNOSIS COMPLETED SUCCESSFULLY!")
    else:
        print("⚠️ Diagnosis completed with warnings")
    print("="*60)
    
    return success


if __name__ == "__main__":
    try:
        trigger_full_diagnosis()
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
