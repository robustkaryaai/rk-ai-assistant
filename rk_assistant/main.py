"""
RK AI Assistant - Simple, Reliable Voice Mode
Minimal main.py that just starts the voice loop.
"""
import sys
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).resolve().parent


def ensure_slug():
    """Get or generate slug."""
    slug_file = BASE_DIR / "slug.txt"
    if slug_file.exists():
        slug = slug_file.read_text().strip()
        if len(slug) == 9 and slug.isdigit():
            return slug
    
    # Generate new slug
    import random
    slug = ''.join([str(random.randint(0, 9)) for _ in range(9)])
    slug_file.write_text(slug)
    return slug


def main():
    """Main entry point - just start voice loop."""
    print("=" * 60)
    print("RK AI ASSISTANT - SIMPLE VOICE MODE")
    print("=" * 60)
    
    # Get slug
    slug = ensure_slug()
    print(f"Device Slug: {slug}")
    
    # Start voice loop
    from .voice_simple import voice_loop
    
    try:
        voice_loop(
            decoder_available=False,  # Not needed for simple mode
            music_proc_holder={},     # Placeholder
            slug=slug
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"FATAL ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
