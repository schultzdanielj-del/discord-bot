"""
Exercise Name Normalization for Three Target Method
Created: February 10, 2026

This module normalizes exercise names according to comprehensive rules
developed through extensive Q&A. Fixes typos, expands abbreviations,
standardizes formatting, and removes duplicate words.
"""

import re
from typing import Optional


def normalize_exercise_name(exercise: str, weight: Optional[float] = None) -> str:
    """
    Normalize an exercise name according to Three Target Method rules.
    
    Args:
        exercise: Raw exercise name from user input
        weight: Weight value (used for squat disambiguation)
        
    Returns:
        Normalized exercise name
        
    Example:
        >>> normalize_exercise_name("db tricep tricep extension")
        'dumbbell tricep extension'
        >>> normalize_exercise_name("weighte dips")
        'weighted dips'
        >>> normalize_exercise_name("squat", weight=135)
        'barbell back squat'
    """
    
    # Skip messages starting with * (coach comments)
    if exercise.strip().startswith('*'):
        return ""
    
    # 1. PREPROCESSING
    exercise = exercise.lower().strip()
    
    # Remove extra whitespace
    exercise = re.sub(r'\s+', ' ', exercise)
    
    # Remove periods, commas
    exercise = exercise.replace('.', '').replace(',', '')
    
    # Remove parentheses and their contents
    exercise = re.sub(r'\([^)]*\)', '', exercise)
    
    # Convert hyphens to spaces
    exercise = exercise.replace('-', ' ')
    
    # Clean up whitespace again after removals
    exercise = re.sub(r'\s+', ' ', exercise).strip()
    
    # 2. TYPO CORRECTIONS
    typo_map = {
        'weighte': 'weighted',
        'ex bar': 'ez bar',
        'dumbell': 'dumbbell',
        'barbel': 'barbell',
        'militery': 'military',
        'millitary': 'military',
        'romainian': 'romanian',
    }
    
    for typo, correction in typo_map.items():
        exercise = exercise.replace(typo, correction)
    
    # 3. STRIP "THE"
    if exercise.startswith('the '):
        exercise = exercise[4:]
    
    # 4. ABBREVIATION EXPANSIONS
    
    # Equipment abbreviations (word boundary aware)
    exercise = re.sub(r'\bdb\b', 'dumbbell', exercise)
    exercise = re.sub(r'\bbb\b', 'barbell', exercise)
    exercise = re.sub(r'\bkb\b', 'kettlebell', exercise)
    exercise = re.sub(r'\bmb\b', 'medicine ball', exercise)
    
    # EZ bar (if not already "ez bar")
    if 'ez' in exercise and 'ez bar' not in exercise:
        exercise = re.sub(r'\bez\b', 'ez bar', exercise)
    
    # Exercise abbreviations
    exercise = re.sub(r'\brdl\b', 'romanian deadlift', exercise)
    exercise = re.sub(r'\bdl\b', 'deadlift', exercise)
    exercise = re.sub(r'\bohp\b', 'overhead press', exercise)
    exercise = re.sub(r'\bbp\b', 'bench press', exercise)
    exercise = re.sub(r'\bfs\b', 'front squat', exercise)
    exercise = re.sub(r'\bbs\b', 'back squat', exercise)
    exercise = re.sub(r'\bghr\b', 'glute ham raise', exercise)
    exercise = re.sub(r'\brdf\b', 'rear delt fly', exercise)
    exercise = re.sub(r'\bcs\b', 'chest supported', exercise)
    exercise = re.sub(r'\bsa\b', 'single arm', exercise)
    exercise = re.sub(r'\bsl\b', 'single leg', exercise)
    exercise = re.sub(r'\bhspu\b', 'handstand pushup', exercise)
    exercise = re.sub(r'\ber\b', 'external rotation', exercise)
    
    # Arm/leg modifiers
    exercise = re.sub(r'\bone arm\b', 'single arm', exercise)
    exercise = re.sub(r'\b1 arm\b', 'single arm', exercise)
    exercise = re.sub(r'\bone leg\b', 'single leg', exercise)
    exercise = re.sub(r'\b1 leg\b', 'single leg', exercise)
    
    # Grip conversions
    exercise = re.sub(r'\bpronated\b', 'overhand', exercise)
    exercise = re.sub(r'\bsupinated\b', 'underhand', exercise)
    exercise = re.sub(r'\bsupine\b', 'lying', exercise)
    
    # OH context-dependent (overhead vs overhand)
    # If OH is paired with pulldown/pullup/row/curl, it's overhand
    if re.search(r'\boh\b.*\b(pulldown|pullup|row|curl)', exercise) or \
       re.search(r'\b(pulldown|pullup|row|curl).*\boh\b', exercise):
        exercise = re.sub(r'\boh\b', 'overhand', exercise)
    else:
        exercise = re.sub(r'\boh\b', 'overhead', exercise)
    
    # UH -> underhand
    exercise = re.sub(r'\buh\b', 'underhand', exercise)
    
    # 5. EQUIPMENT SYNONYM NORMALIZATION
    
    # Suspension trainer
    exercise = re.sub(r'\bsuspension trainer\b', 'trx', exercise)
    exercise = re.sub(r'\bsuspension\b', 'trx', exercise)
    
    # Cable
    exercise = re.sub(r'\bcables\b', 'cable', exercise)
    
    # EZ bar variations
    exercise = re.sub(r'\bez curl bar\b', 'ez bar', exercise)
    exercise = re.sub(r'\beasy bar\b', 'ez bar', exercise)
    
    # Smith machine
    exercise = re.sub(r'\bsmith\b(?! machine)', 'smith machine', exercise)
    
    # Toe press = leg press calf raise
    exercise = re.sub(r'\btoe press\b', 'leg press calf raise', exercise)
    
    # Ball leg curl variations
    exercise = re.sub(r'\bswiss ball leg curl\b', 'stability ball leg curl', exercise)
    exercise = re.sub(r'\bball leg curl\b', 'stability ball leg curl', exercise)
    exercise = re.sub(r'\bgliding disk leg curl\b', 'slider leg curl', exercise)
    exercise = re.sub(r'\bgliding leg curl\b', 'slider leg curl', exercise)
    exercise = re.sub(r'\btowel leg curl\b', 'slider leg curl', exercise)
    
    # Band assistance
    exercise = re.sub(r'\bband assisted\b', 'band assisted', exercise)
    if 'chinup' in exercise or 'pullup' in exercise:
        exercise = re.sub(r'\bbanded\b', 'band assisted', exercise)
    
    # 6. COMPOUND WORD NORMALIZATION (remove spaces)
    compound_words = [
        ('chin up', 'chinup'),
        ('pull up', 'pullup'),
        ('push up', 'pushup'),
        ('sit up', 'situp'),
        ('step up', 'stepup'),
        ('face pull', 'facepull'),
        ('push down', 'pushdown'),
        ('pull down', 'pulldown'),
    ]
    
    for spaced, compound in compound_words:
        exercise = exercise.replace(spaced, compound)
    
    # 7. POSITION & MODIFIER STANDARDIZATION
    
    # Pause variations
    exercise = re.sub(r'\bpause rep\b', 'paused', exercise)
    
    # 8. EXERCISE-SPECIFIC RULES
    
    # Lateral raises - add "raise" if not present
    if 'lateral' in exercise and 'raise' not in exercise:
        exercise = re.sub(r'\blateral(s)?\b', 'lateral raise', exercise)
    exercise = re.sub(r'\blat raise(s)?\b', 'lateral raise', exercise)
    
    # Extensions - normalize plural and add "tricep" if appropriate
    exercise = re.sub(r'\bextensions\b', 'extension', exercise)
    exercise = re.sub(r'\btriceps\b', 'tricep', exercise)
    
    if 'extension' in exercise and 'tricep' not in exercise:
        # Don't add tricep if it's leg/back/hip/hyper/reverse extension
        if not re.search(r'\b(leg|back|hip|hyper|reverse)\b', exercise):
            exercise = re.sub(r'\bextension\b', 'tricep extension', exercise)
    
    # Back extension variations
    exercise = re.sub(r'\bhyperextension\b', 'back extension', exercise)
    exercise = re.sub(r'\bhyper\b(?! extension)', 'back extension', exercise)
    
    # Reverse hyper variations
    exercise = re.sub(r'\breverse hyper extension\b', 'reverse hyper', exercise)
    exercise = re.sub(r'\breverse hyperextension\b', 'reverse hyper', exercise)
    
    # Curls - default to bicep curl if just "curl"
    if exercise == 'curl' or exercise == 'curls':
        exercise = 'bicep curl'
    exercise = re.sub(r'\bbiceps curl\b', 'bicep curl', exercise)
    exercise = re.sub(r'\bcable curl\b', 'cable bicep curl', exercise)
    
    # Presses - Chest
    # Complete "bench" to "bench press" if press is missing
    if 'bench' in exercise and 'press' not in exercise and 'bench press' not in exercise:
        exercise = re.sub(r'\bbench\b', 'bench press', exercise)
    
    exercise = re.sub(r'\bflat bench press\b', 'bench press', exercise)
    exercise = re.sub(r'\bincline press\b', 'incline bench press', exercise)
    exercise = re.sub(r'\bdecline press\b', 'decline bench press', exercise)
    
    # Presses - Shoulder
    exercise = re.sub(r'\bshoulder press\b', 'military press', exercise)
    exercise = re.sub(r'\boverhead press\b', 'military press', exercise)
    
    # Rows
    exercise = re.sub(r'\bbent over barbell row\b', 'barbell row', exercise)
    exercise = re.sub(r'\bbent row\b', 'barbell row', exercise)
    
    # DB row defaults to single arm
    if re.match(r'^dumbbell row$', exercise):
        exercise = 'single arm dumbbell row'
    exercise = re.sub(r'\bone arm dumbbell row\b', 'single arm dumbbell row', exercise)
    
    # Bent dumbbell row is double arm
    exercise = re.sub(r'\bbent dumbbell row\b', 'bent over dumbbell row', exercise)
    exercise = re.sub(r'\bbent over dumbbell row\b', 'bent over dumbbell row', exercise)
    
    # Pulldowns
    if re.match(r'^pulldown$', exercise):
        exercise = 'lat pulldown'
    exercise = re.sub(r'\bwide grip pulldown\b', 'wide grip lat pulldown', exercise)
    exercise = re.sub(r'\bwide pulldown\b', 'wide grip lat pulldown', exercise)
    exercise = re.sub(r'\bclose grip pulldown\b', 'close grip lat pulldown', exercise)
    exercise = re.sub(r'\bclose pulldown\b', 'close grip lat pulldown', exercise)
    
    # Pullups/Chinups
    exercise = re.sub(r'\bpulls\b', 'pullup', exercise)
    exercise = re.sub(r'\bchins\b', 'chinup', exercise)
    
    # Squats - weight-based logic
    if weight is not None and 'squat' in exercise:
        # If just "squat" with no modifiers
        if re.match(r'^squat$', exercise):
            if weight == 0:
                exercise = 'bodyweight squat'
            elif weight > 15:
                exercise = 'barbell back squat'
    
    # Goblet squat normalization
    exercise = re.sub(r'\bdumbbell goblet squat\b', 'goblet squat', exercise)
    exercise = re.sub(r'\bkettlebell goblet squat\b', 'goblet squat', exercise)
    
    # Bulgarian split squat
    exercise = re.sub(r'\bbulgarian split squat\b', 'rear foot elevated split squat', exercise)
    
    # Deadlifts
    if re.match(r'^deadlift$', exercise):
        exercise = 'conventional deadlift'
    exercise = re.sub(r'\bsumo\b(?! deadlift)', 'sumo deadlift', exercise)
    exercise = re.sub(r'\bhex bar deadlift\b', 'trap bar deadlift', exercise)
    
    # Hip thrusts
    exercise = re.sub(r'\bbarbell hip thrust\b', 'hip thrust', exercise)
    
    # Dips - plural default
    if re.match(r'^dip$', exercise):
        exercise = 'dips'
    exercise = re.sub(r'\bparallel bar dip(s)?\b', 'dips', exercise)
    
    # Facepulls
    exercise = re.sub(r'\bcable facepull\b', 'facepull', exercise)
    exercise = re.sub(r'\brope facepull\b', 'facepull', exercise)
    
    # Flies
    exercise = re.sub(r'\bflye(s)?\b', 'fly', exercise)
    exercise = re.sub(r'\bpec deck\b', 'machine fly', exercise)
    exercise = re.sub(r'\breverse fly\b', 'rear delt fly', exercise)
    exercise = re.sub(r'\bbent over fly\b', 'rear delt fly', exercise)
    exercise = re.sub(r'\brear fly\b', 'rear delt fly', exercise)
    
    # Shrugs
    exercise = re.sub(r'\btrap shrug\b', 'shrug', exercise)
    
    # Calf raises
    exercise = re.sub(r'\bcalf raises\b', 'calf raise', exercise)
    if re.match(r'^calf raise$', exercise):
        exercise = 'standing calf raise'
    
    # Situps
    exercise = re.sub(r'\bsit up\b', 'situp', exercise)
    
    # Ab work
    exercise = re.sub(r'\bab wheel rollout\b', 'ab rollout', exercise)
    exercise = re.sub(r'\bab wheel\b', 'ab rollout', exercise)
    if re.match(r'^rollout$', exercise):
        exercise = 'ab rollout'
    
    exercise = re.sub(r'\bhang from bar\b', 'dead hang', exercise)
    exercise = re.sub(r'\bbar hang\b', 'dead hang', exercise)
    
    # Tricep pushdowns
    if re.match(r'^pushdown$', exercise):
        exercise = 'tricep pushdown'
    # V-bar and ez bar pushdowns = same as straight bar (default)
    exercise = re.sub(r'\bv bar pushdown\b', 'tricep pushdown', exercise)
    exercise = re.sub(r'\bv-bar pushdown\b', 'tricep pushdown', exercise)
    exercise = re.sub(r'\bez bar pushdown\b', 'tricep pushdown', exercise)
    
    # Good mornings
    exercise = re.sub(r'\bbarbell good morning\b', 'good morning', exercise)
    
    # Pullovers
    if re.match(r'^pullover$', exercise):
        exercise = 'dumbbell pullover'
    exercise = re.sub(r'\bstraight arm pulldown\b', 'cable pullover', exercise)
    
    # Machine exercises - normalize format
    exercise = re.sub(r'\bchest press machine\b', 'machine chest press', exercise)
    
    # External rotation
    exercise = re.sub(r'\bext rotation\b', 'external rotation', exercise)
    
    # Strip tempo notation (pattern: number-number-number)
    exercise = re.sub(r'\b\d+-\d+-\d+\b', '', exercise)
    
    # 9. INCLINE ANGLE NORMALIZATION (presses only)
    if 'press' in exercise:
        # Low incline
        exercise = re.sub(r'\b(30 degree|low) incline\b', 'low incline', exercise)
        # High incline  
        exercise = re.sub(r'\b(60 degree|high|steep) incline\b', 'high incline', exercise)
        # Standard incline
        exercise = re.sub(r'\b45 degree incline\b', 'incline', exercise)
    
    # 10. REMOVE DUPLICATE CONSECUTIVE WORDS
    words = exercise.split()
    if words:
        deduplicated = [words[0]]
        for i in range(1, len(words)):
            if words[i] != words[i-1]:
                deduplicated.append(words[i])
        exercise = ' '.join(deduplicated)
    
    # Final cleanup
    exercise = exercise.strip()
    
    return exercise


if __name__ == "__main__":
    # Test cases for known bad data
    test_cases = [
        ("dumbbell tricep tricep extension", "dumbbell tricep extension"),
        ("trx tricep tricep extension", "trx tricep extension"),
        ("incline ex bar triceps extensions", "incline ez bar tricep extension"),
        ("weighte dips", "weighted dips"),
        ("lateral raise raise", "lateral raise"),
        ("db bench", "dumbbell bench"),
        ("bb row", "barbell row"),
        ("squat", "squat"),  # Without weight context
        ("chin up", "chinup"),
        ("the bench press", "bench press"),
        ("bent row", "barbell row"),
        ("cable curl", "cable bicep curl"),
        ("face pull", "facepull"),
    ]
    
    print("Testing normalize_exercise_name():\n")
    for input_ex, expected in test_cases:
        result = normalize_exercise_name(input_ex)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{input_ex}' -> '{result}' (expected: '{expected}')")
    
    # Test with weight context
    print("\n\nTesting with weight context:")
    print(f"squat (weight=0): {normalize_exercise_name('squat', weight=0)}")
    print(f"squat (weight=135): {normalize_exercise_name('squat', weight=135)}")
    print(f"squat (weight=10): {normalize_exercise_name('squat', weight=10)}")
