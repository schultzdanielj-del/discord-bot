"""
Fuzzy Matching for Exercise Names Against User Programs
Created: February 10, 2026

This module matches user-typed exercise names against their assigned program
using fuzzy string matching with the RapidFuzz library.
"""

from rapidfuzz import fuzz
from typing import List, Tuple, Optional
from exercise_normalization import normalize_exercise_name


def get_canonical_exercise_name(
    user_input: str,
    program_exercises: List[str],
    weight: Optional[float] = None,
    threshold: int = 85
) -> Tuple[str, int, bool]:
    """
    Match user input against their program exercises using fuzzy matching.
    
    Args:
        user_input: Raw exercise name from user
        program_exercises: List of canonical exercise names from user's program
                          (all workouts A, B, C, D, E combined)
        weight: Weight value for context (used in normalization)
        threshold: Minimum similarity score (0-100) for matching
        
    Returns:
        Tuple of (canonical_name, match_score, used_fuzzy_match)
        - canonical_name: The matched exercise name (or normalized input if no match)
        - match_score: Similarity score (0-100)
        - used_fuzzy_match: True if fuzzy matched, False if no match or exact
        
    Example:
        >>> program = ["dumbbell bench press", "chinup", "goblet squat"]
        >>> get_canonical_exercise_name("db bench", program)
        ('dumbbell bench press', 95, True)
        >>> get_canonical_exercise_name("random exercise", program)
        ('random exercise', 0, False)
    """
    
    # First normalize the user input
    normalized_input = normalize_exercise_name(user_input, weight=weight)
    
    # If normalization returned empty (e.g., message starting with *), return empty
    if not normalized_input:
        return ("", 0, False)
    
    # Check for exact match first (after normalization)
    if normalized_input in program_exercises:
        return (normalized_input, 100, False)
    
    # Find best fuzzy match
    best_match = None
    best_score = 0
    
    for program_exercise in program_exercises:
        # Use fuzz.ratio for similarity scoring
        score = fuzz.ratio(normalized_input, program_exercise)
        
        if score > best_score:
            best_score = score
            best_match = program_exercise
    
    # Apply threshold rules
    if best_score >= threshold:
        # 85%+ similarity: Use canonical name from program
        return (best_match, best_score, True)
    elif best_score >= 70:
        # 70-84% similarity: Store as-is (edge case)
        return (normalized_input, best_score, False)
    else:
        # Under 70% similarity: Store as-is (off-program work)
        return (normalized_input, best_score, False)


def get_canonical_with_tiebreaker(
    user_input: str,
    program_exercises: List[str],
    weight: Optional[float] = None,
    threshold: int = 85
) -> Tuple[str, int, bool]:
    """
    Match with tie-breaking logic: if multiple exercises match equally well,
    use the one that appears first in the program (users log in order).
    
    Args:
        Same as get_canonical_exercise_name
        
    Returns:
        Same as get_canonical_exercise_name
    """
    
    # First normalize the user input
    normalized_input = normalize_exercise_name(user_input, weight=weight)
    
    if not normalized_input:
        return ("", 0, False)
    
    # Check for exact match first
    if normalized_input in program_exercises:
        return (normalized_input, 100, False)
    
    # Find ALL matches at each score level
    matches_by_score = {}
    
    for program_exercise in program_exercises:
        score = fuzz.ratio(normalized_input, program_exercise)
        
        if score not in matches_by_score:
            matches_by_score[score] = []
        matches_by_score[score].append(program_exercise)
    
    # Get the highest score
    if not matches_by_score:
        return (normalized_input, 0, False)
    
    best_score = max(matches_by_score.keys())
    best_matches = matches_by_score[best_score]
    
    # If tie, take the FIRST one in program order
    # (program_exercises list is already in workout order A, B, C, D, E)
    best_match = best_matches[0]
    
    # Apply threshold rules
    if best_score >= threshold:
        return (best_match, best_score, True)
    elif best_score >= 70:
        return (normalized_input, best_score, False)
    else:
        return (normalized_input, best_score, False)


def parse_pr_message(message: str, program_exercises: List[str]) -> Optional[dict]:
    """
    Parse a PR message from Discord into structured data.
    
    Expected format: "exercise weight/reps" or "exercise BW/reps"
    Examples:
        - "db bench 85/12"
        - "chinup BW/8"
        - "goblet squat 70/15"
        
    Args:
        message: Raw Discord message
        program_exercises: User's program for fuzzy matching
        
    Returns:
        Dictionary with parsed data, or None if invalid
        {
            'raw_exercise': str,
            'canonical_exercise': str,
            'weight': float,
            'reps': int,
            'estimated_1rm': float,
            'match_score': int,
            'used_fuzzy': bool
        }
    """
    
    # Skip messages starting with *
    if message.strip().startswith('*'):
        return None
    
    # Basic pattern: exercise weight/reps or exercise BW/reps
    # More flexible pattern to handle various formats
    pattern = r'^(.+?)\s+([0-9]+\.?[0-9]*|bw|BW)\s*/\s*([0-9]+)$'
    
    import re
    match = re.match(pattern, message.strip())
    
    if not match:
        return None
    
    raw_exercise = match.group(1).strip()
    weight_str = match.group(2).strip()
    reps_str = match.group(3).strip()
    
    # Parse weight
    if weight_str.upper() == 'BW':
        weight = 0.0
    else:
        try:
            weight = float(weight_str)
        except ValueError:
            return None
    
    # Parse reps
    try:
        reps = int(reps_str)
    except ValueError:
        return None
    
    # Validate ranges
    if weight < 0 or weight > 1000:
        return None
    if reps < 3 or reps > 50:
        return None
    
    # Get canonical exercise name with fuzzy matching
    canonical, score, used_fuzzy = get_canonical_with_tiebreaker(
        raw_exercise,
        program_exercises,
        weight=weight
    )
    
    if not canonical:
        return None
    
    # Calculate estimated 1RM (Epley formula)
    # e1RM = weight × (1 + reps/30)
    if weight == 0:  # Bodyweight
        estimated_1rm = 0.0  # Don't calculate e1RM for bodyweight
    else:
        estimated_1rm = weight * (1 + reps / 30)
    
    return {
        'raw_exercise': raw_exercise,
        'canonical_exercise': canonical,
        'weight': weight,
        'reps': reps,
        'estimated_1rm': estimated_1rm,
        'match_score': score,
        'used_fuzzy': used_fuzzy
    }


if __name__ == "__main__":
    # Test fuzzy matching
    print("Testing Fuzzy Matching:\n")
    
    # Sample program
    program = [
        "dumbbell bench press",
        "chinup",
        "goblet squat",
        "single arm dumbbell row",
        "lateral raise",
        "tricep extension",
        "atg split squat",
    ]
    
    test_cases = [
        ("db bench", "dumbbell bench press"),  # Should match
        ("chin up", "chinup"),  # Should match after normalization
        ("db tricep extension", "dumbbell tricep extension"),  # Exact after normalization
        ("tricep extension", "tricep extension"),  # Would need fuzzy to match program
        ("squat", "squat"),  # Without weight, stays as-is (doesn't match goblet well)
        ("overhead press", "military press"),  # Normalizes to military press
        ("laterals", "lateral raise"),  # Should match
        ("1 arm db row", "single arm dumbbell row"),  # Should match
    ]
    
    print("Program exercises:")
    for i, ex in enumerate(program, 1):
        print(f"  {i}. {ex}")
    print()
    
    for user_input, expected in test_cases:
        canonical, score, fuzzy = get_canonical_with_tiebreaker(user_input, program)
        status = "✓" if canonical == expected else "✗"
        fuzzy_str = "(fuzzy)" if fuzzy else "(exact/no-match)"
        print(f"{status} '{user_input}' -> '{canonical}' [score: {score}] {fuzzy_str}")
        if expected and canonical != expected:
            print(f"   Expected: '{expected}'")
    
    print("\n\nTesting PR Message Parsing:\n")
    
    messages = [
        "db bench 85/12",
        "chinup BW/8",
        "goblet squat 70/15",
        "laterals 25/15",
        "* this is a comment, should be ignored",
        "invalid message format",
    ]
    
    for msg in messages:
        result = parse_pr_message(msg, program)
        if result:
            print(f"✓ '{msg}'")
            print(f"  Exercise: {result['canonical_exercise']}")
            print(f"  Weight: {result['weight']}, Reps: {result['reps']}")
            print(f"  E1RM: {result['estimated_1rm']:.1f}")
            print(f"  Match score: {result['match_score']} (fuzzy: {result['used_fuzzy']})")
        else:
            print(f"✗ '{msg}' - Could not parse")
        print()
