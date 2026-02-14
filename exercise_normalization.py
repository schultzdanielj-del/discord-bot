"""
Exercise Name Normalization for Three Target Method
Created: February 10, 2026
Updated: February 14, 2026

This module normalizes exercise names according to comprehensive rules
developed through extensive Q&A (~100 questions). Fixes typos, expands
abbreviations, standardizes formatting, and removes duplicate words.

This is the canonical normalization function. The same logic is embedded
in scrape_and_reload.py (in ttm-metrics-api repo). Any changes here
must be mirrored there.
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
    """

    # Skip messages starting with * (coach comments)
    if exercise.strip().startswith('*'):
        return ""

    # 1. PREPROCESSING
    exercise = exercise.lower().strip()
    exercise = re.sub(r'\s+', ' ', exercise)
    exercise = exercise.replace('.', '').replace(',', '')
    exercise = re.sub(r'\([^)]*\)', '', exercise)
    exercise = exercise.replace('-', ' ')
    exercise = re.sub(r'\s+', ' ', exercise).strip()

    # 2. TYPO CORRECTIONS (word-boundary aware)
    typo_map = [
        (r'\bweighte\b', 'weighted'),
        (r'\bex bar\b', 'ez bar'),
        (r'\bdumbell\b', 'dumbbell'),
        (r'\bbarbel\b', 'barbell'),
        (r'\bmilitery\b', 'military'),
        (r'\bmillitary\b', 'military'),
        (r'\bromainian\b', 'romanian'),
        (r'\bromaninan\b', 'romanian'),
        (r'\bstragiht\b', 'straight'),
        (r'\bskullcrushers?\b', 'tricep extension'),
    ]
    for pattern, correction in typo_map:
        exercise = re.sub(pattern, correction, exercise)

    # 3. STRIP "THE"
    if exercise.startswith('the '):
        exercise = exercise[4:]

    # 4. ABBREVIATION EXPANSIONS

    # Equipment abbreviations
    exercise = re.sub(r'\bdb\b', 'dumbbell', exercise)
    exercise = re.sub(r'\bbb\b', 'barbell', exercise)
    exercise = re.sub(r'\bbw\b', 'bodyweight', exercise)
    exercise = re.sub(r'\bkb\b', 'kettlebell', exercise)
    exercise = re.sub(r'\bmb\b', 'medicine ball', exercise)
    exercise = re.sub(r'\bsl\b', 'single leg', exercise)
    exercise = re.sub(r'\bsa\b', 'single arm', exercise)
    exercise = re.sub(r'\bcs\b', 'chest supported', exercise)
    exercise = re.sub(r'\bhs\b', 'head supported', exercise)
    exercise = re.sub(r'\bdm\b', 'dumbbell', exercise)

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
    if re.search(r'\boh\b.*\b(pulldown|pullup|row|curl)', exercise) or \
       re.search(r'\b(pulldown|pullup|row|curl).*\boh\b', exercise):
        exercise = re.sub(r'\boh\b', 'overhand', exercise)
    else:
        exercise = re.sub(r'\boh\b', 'overhead', exercise)

    # UH -> underhand
    exercise = re.sub(r'\buh\b', 'underhand', exercise)

    # 5. EQUIPMENT SYNONYM NORMALIZATION

    exercise = re.sub(r'\bsuspension trainer\b', 'trx', exercise)
    exercise = re.sub(r'\bsuspension\b', 'trx', exercise)
    exercise = re.sub(r'\bcables\b', 'cable', exercise)
    exercise = re.sub(r'\bez curl bar\b', 'ez bar', exercise)
    exercise = re.sub(r'\beasy bar\b', 'ez bar', exercise)
    exercise = re.sub(r'\bsmith\b(?! machine)', 'smith machine', exercise)
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

    # 6. COMPOUND WORD NORMALIZATION
    compound_words = [
        ('chin up', 'chinup'), ('chin ups', 'chinups'),
        ('pull up', 'pullup'), ('pull ups', 'pullups'),
        ('push up', 'pushup'), ('push ups', 'pushups'),
        ('sit up', 'situp'), ('sit ups', 'situps'),
        ('step up', 'stepup'), ('step ups', 'stepups'),
        ('face pull', 'facepull'), ('face pulls', 'facepulls'),
        ('push down', 'pushdown'), ('push downs', 'pushdowns'),
        ('pull down', 'pulldown'), ('pull downs', 'pulldowns'),
    ]
    for spaced, compound in compound_words:
        exercise = exercise.replace(spaced, compound)

    # 7. PLURAL NORMALIZATION
    plural_map = [
        (r'\braises\b', 'raise'),
        (r'\bextensions\b', 'extension'),
        (r'\bcurls\b', 'curl'),
        (r'\brows\b', 'row'),
        (r'\bpresses\b', 'press'),
        (r'\bflies\b', 'fly'),
        (r'\bshrugs\b', 'shrug'),
        (r'\bsquats\b', 'squat'),
        (r'\blunges\b', 'lunge'),
        (r'\bplanks\b', 'plank'),
        (r'\brotations\b', 'rotation'),
        (r'\bmines\b', 'mine'),
        (r'\bpullups\b', 'pullup'),
        (r'\bchinups\b', 'chinup'),
        (r'\bpushups\b', 'pushup'),
        (r'\bdips\b', 'dip'),
        (r'\bpushdowns\b', 'pushdown'),
        (r'\bpulldowns\b', 'pulldown'),
        (r'\bfacepulls\b', 'facepull'),
        (r'\bstepups\b', 'stepup'),
        (r'\bsitups\b', 'situp'),
        (r'\bdeadlifts\b', 'deadlift'),
        (r'\bthrusts\b', 'thrust'),
        (r'\brollouts\b', 'rollout'),
        (r'\bbridges\b', 'bridge'),
        (r'\bangels\b', 'angel'),
        (r'\blandmines\b', 'landmine'),
        (r'\bhypers\b', 'hyper'),
        (r'\bdeadbugs\b', 'deadbug'),
    ]
    for pattern, replacement in plural_map:
        exercise = re.sub(pattern, replacement, exercise)

    # 8. POSITION & MODIFIER STANDARDIZATION
    exercise = re.sub(r'\bpause rep\b', 'paused', exercise)
    exercise = re.sub(r'\bunderhand grip\b', 'underhand', exercise)
    exercise = re.sub(r'\boverhand grip\b', 'overhand', exercise)
    exercise = re.sub(r'\bbody weight\b', 'bodyweight', exercise)
    exercise = re.sub(r'\bland mine\b', 'landmine', exercise)
    exercise = re.sub(r'\bglut\b', 'glute', exercise)

    # Reorder "dumbbell seated/standing/incline" to "seated/standing/incline dumbbell"
    exercise = re.sub(r'\bdumbbell (seated|standing|incline|flat|decline)\b', r'\1 dumbbell', exercise)

    # "bench" without "press" -> "bench press"
    if exercise.endswith(' bench') and 'press' not in exercise:
        exercise = exercise + ' press'
    if 'bench' in exercise and 'press' not in exercise and 'bench press' not in exercise:
        exercise = re.sub(r'\bbench\b', 'bench press', exercise)

    # 9. TRX EXERCISE NORMALIZATION
    exercise = re.sub(r'\btrx bicep tricep\b', 'trx tricep', exercise)
    exercise = re.sub(r'\btrx bicep curl tricep\b', 'trx tricep', exercise)
    if re.search(r'\btrx bicep\b', exercise) and 'curl' not in exercise:
        exercise = re.sub(r'\btrx bicep\b', 'trx bicep curl', exercise)
    if re.search(r'\btrx tricep\b', exercise) and 'extension' not in exercise:
        exercise = re.sub(r'\btrx tricep\b', 'trx tricep extension', exercise)

    # 10. STRIP TRAILING MODIFIERS
    exercise = re.sub(r'\s+\d+\s*second.*$', '', exercise)
    exercise = re.sub(r'\s+(each|per)\s+side$', '', exercise)
    exercise = re.sub(r'\s+x\d+$', '', exercise)

    # 11. EXERCISE-SPECIFIC RULES

    # Lateral raises
    if 'lateral' in exercise and 'raise' not in exercise:
        exercise = re.sub(r'\blateral(s)?\b', 'lateral raise', exercise)
    exercise = re.sub(r'\blat raise(s)?\b', 'lateral raise', exercise)

    # Extensions - add "tricep" if not leg/back/hip/hyper/reverse
    if 'extension' in exercise and 'tricep' not in exercise:
        if not re.search(r'\b(leg|back|hip|hyper|reverse)\b', exercise):
            exercise = re.sub(r'\bextension(s)?\b', 'tricep extension', exercise)

    exercise = re.sub(r'\btriceps\b', 'tricep', exercise)

    # Back extensions / hypers
    exercise = re.sub(r'\bhyperextension\b', 'back extension', exercise)
    exercise = re.sub(r'\bhyper\b(?! extension)', 'back extension', exercise)

    # Reverse hyper
    exercise = re.sub(r'\breverse hyper extension\b', 'reverse hyper', exercise)
    exercise = re.sub(r'\breverse hyperextension\b', 'reverse hyper', exercise)

    # Curls
    if exercise == 'curl' or exercise == 'curls':
        exercise = 'bicep curl'
    exercise = re.sub(r'\bbiceps curl\b', 'bicep curl', exercise)
    exercise = re.sub(r'\bcable curl\b', 'cable bicep curl', exercise)

    # Presses - Chest
    exercise = re.sub(r'\bflat bench press\b', 'bench press', exercise)
    exercise = re.sub(r'\bincline press\b', 'incline bench press', exercise)
    exercise = re.sub(r'\bdecline press\b', 'decline bench press', exercise)
    if 'dumbbell' in exercise and 'press' in exercise and 'bench' not in exercise and 'military' not in exercise:
        exercise = exercise.replace('dumbbell press', 'dumbbell bench press')

    # Presses - Shoulder
    exercise = re.sub(r'\bshoulder press\b', 'military press', exercise)
    exercise = re.sub(r'\boverhead press\b', 'military press', exercise)

    # Rows
    exercise = re.sub(r'\bbent over barbell row\b', 'barbell row', exercise)
    exercise = re.sub(r'\bbent row\b', 'barbell row', exercise)

    if re.match(r'^dumbbell row$', exercise):
        exercise = 'single arm dumbbell row'
    exercise = re.sub(r'\bone arm dumbbell row\b', 'single arm dumbbell row', exercise)
    exercise = re.sub(r'\bbent dumbbell row\b', 'bent over dumbbell row', exercise)

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

    # Squats - weight-based disambiguation
    if weight is not None and 'squat' in exercise:
        if re.match(r'^squat$', exercise):
            if weight == 0:
                exercise = 'bodyweight squat'
            elif weight > 15:
                exercise = 'barbell back squat'

    exercise = re.sub(r'\bdumbbell goblet squat\b', 'goblet squat', exercise)
    exercise = re.sub(r'\bkettlebell goblet squat\b', 'goblet squat', exercise)
    exercise = re.sub(r'\bbulgarian split squat\b', 'rear foot elevated split squat', exercise)

    # Deadlifts
    if re.match(r'^deadlift$', exercise):
        exercise = 'conventional deadlift'
    exercise = re.sub(r'\bsumo\b(?! deadlift)', 'sumo deadlift', exercise)
    exercise = re.sub(r'\bhex bar deadlift\b', 'trap bar deadlift', exercise)

    # Hip thrusts
    exercise = re.sub(r'\bbarbell hip thrust\b', 'hip thrust', exercise)

    # Dips
    exercise = re.sub(r'\bparallel bar dip\b', 'dip', exercise)

    # Facepulls
    exercise = re.sub(r'\bcable facepull\b', 'facepull', exercise)
    exercise = re.sub(r'\brope facepull\b', 'facepull', exercise)

    # Flies
    exercise = re.sub(r'\bflye(s)?\b', 'fly', exercise)
    exercise = re.sub(r'\bflys\b', 'fly', exercise)
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

    # Ab work
    exercise = re.sub(r'\bab wheel rollout\b', 'ab rollout', exercise)
    exercise = re.sub(r'\bab wheel rotation\b', 'ab rollout', exercise)
    if re.match(r'^ab wheel$', exercise):
        exercise = 'ab rollout'
    if re.match(r'^rollout$', exercise):
        exercise = 'ab rollout'

    # Hangs
    exercise = re.sub(r'\bhang from bar\b', 'dead hang', exercise)
    exercise = re.sub(r'\bbar hang\b', 'dead hang', exercise)

    # Tricep pushdowns
    if re.match(r'^pushdown(s)?$', exercise):
        exercise = 'tricep pushdown'
    exercise = re.sub(r'\bv bar pushdown\b', 'tricep pushdown', exercise)
    exercise = re.sub(r'\bv.bar pushdown\b', 'tricep pushdown', exercise)
    exercise = re.sub(r'\bv-bar pushdown\b', 'tricep pushdown', exercise)
    exercise = re.sub(r'\bez bar pushdown\b', 'tricep pushdown', exercise)

    exercise = re.sub(r'\bpushdowns\b', 'pushdown', exercise)

    # Good mornings
    exercise = re.sub(r'\bbarbell good morning\b', 'good morning', exercise)

    # Pullovers
    if re.match(r'^pullover$', exercise):
        exercise = 'dumbbell pullover'
    exercise = re.sub(r'\bstraight arm pulldown\b', 'cable pullover', exercise)

    # Machine exercises
    exercise = re.sub(r'\bchest press machine\b', 'machine chest press', exercise)

    # External rotation
    exercise = re.sub(r'\bext rotation\b', 'external rotation', exercise)

    # Strip tempo notation (3-1-3, etc.)
    exercise = re.sub(r'\b\d+ \d+ \d+\b', '', exercise)
    exercise = re.sub(r'\b\d+-\d+-\d+\b', '', exercise)

    # 12. INCLINE ANGLE NORMALIZATION (presses only)
    if 'press' in exercise:
        exercise = re.sub(r'\b(30 degree|low) incline\b', 'low incline', exercise)
        exercise = re.sub(r'\b(60 degree|high|steep) incline\b', 'high incline', exercise)
        exercise = re.sub(r'\b45 degree incline\b', 'incline', exercise)

    # 13. REMOVE DUPLICATE CONSECUTIVE WORDS
    words = exercise.split()
    if words:
        deduplicated = [words[0]]
        for i in range(1, len(words)):
            if words[i] != words[i-1]:
                deduplicated.append(words[i])
        exercise = ' '.join(deduplicated)

    # Final cleanup
    exercise = re.sub(r'\s+', ' ', exercise).strip()
    return exercise


if __name__ == "__main__":
    test_cases = [
        ("dumbbell tricep tricep extension", "dumbbell tricep extension"),
        ("trx tricep tricep extension", "trx tricep extension"),
        ("incline ex bar triceps extensions", "incline ez bar tricep extension"),
        ("weighte dips", "weighted dip"),
        ("lateral raise raise", "lateral raise"),
        ("db bench", "dumbbell bench press"),
        ("bb row", "barbell row"),
        ("chin up", "chinup"),
        ("the bench press", "bench press"),
        ("bent row", "barbell row"),
        ("cable curl", "cable bicep curl"),
        ("face pull", "facepull"),
        ("skullcrushers 85/12", "tricep extension 85/12"),
        ("romaninan deadlift", "romanian deadlift"),
        ("stragiht bar curl", "straight bar curl"),
        ("trx bicep 25/12", "trx bicep curl 25/12"),
        ("trx tricep 25/12", "trx tricep extension 25/12"),
    ]

    print("Testing normalize_exercise_name():\n")
    for input_ex, expected in test_cases:
        result = normalize_exercise_name(input_ex)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{input_ex}' -> '{result}' (expected: '{expected}')")

    print("\n\nTesting with weight context:")
    print(f"squat (weight=0): {normalize_exercise_name('squat', weight=0)}")
    print(f"squat (weight=135): {normalize_exercise_name('squat', weight=135)}")
    print(f"squat (weight=10): {normalize_exercise_name('squat', weight=10)}")
