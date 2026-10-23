"""The case file: suspects, evidence, logs and rooms for "Death at Larkspur Manor".

Keep every string short. Decider has a 4K-token window and the sheet, secret and
statement all go into it on guard calls.
"""
from dataclasses import dataclass, field


@dataclass
class Suspect:
    id: str
    name: str
    persona: str
    facts: str          # truths + prepared cover story: the ONLY things they may claim
    secret: str
    guilty: bool
    seed_memories: list[str] = field(default_factory=list)
    mock_lines: dict = field(default_factory=dict)   # stance -> line, used only when MOCK=1
    followups: list = field(default_factory=list)    # (button label, cross-question) offered after a reply


SUSPECTS = {
    "marcus": Suspect(
        id="marcus", name="Marcus Hale",
        persona="Gruff night-shift caretaker, short sentences, avoids eye contact.",
        facts=("Works nights at Larkspur Manor. Was in the boiler room 9pm-midnight "
               "(cover story). Knows the victim, Mr. Ashworth, as the owner. "
               "Found the study door locked at 11:40pm."),
        secret="He left the boiler room at 10:30pm to meet Ashworth in the study and argued over unpaid wages.",
        guilty=True,
        seed_memories=["I told everyone I was in the boiler room from 9pm to midnight.",
                       "I found the study door locked at 11:40pm."],
        followups=[('Press the alibi', 'Marcus, can anyone confirm you were in the boiler room all night?'),
                   ('The study door', 'Why did you try the study door at 11:40?'),
                   ('His wages', 'Are you owed wages, Marcus? How did you feel about Mr. Ashworth?'),
                   ('Who else?', 'Who else did you see in the house tonight?')],
        mock_lines={
            "truthful": "Caretaker. Nights. Been here six years.",
            "deflect": "Ask the housekeeper. She sees more than I do.",
            "lie": "Boiler room. Nine till midnight. Never left.",
            "crack": "I... went up to the study. Just to talk. About my wages. That's all.",
        },
    ),
    "eleanor": Suspect(
        id="eleanor", name="Eleanor Voss",
        persona="Prim housekeeper, formal, corrects people, hides worry behind manners.",
        facts=("Housekeeper at Larkspur Manor for twelve years. Says she was in her room "
               "from 9pm and went to bed early (cover story). Heard raised voices near the study "
               "around 10:40pm."),
        secret="She slipped out at 10pm to pawn a silver candlestick in the village to cover her sister's debt.",
        guilty=False,
        seed_memories=["I told the police I went to bed early.",
                       "I heard raised voices near the study around 10:40pm."],
        followups=[('Raised voices', 'Who did you hear arguing near the study at 10:40?'),
                   ('Press the alibi', 'Can anyone confirm you went to bed early, Miss Voss?'),
                   ('On Marcus', 'What do you make of Marcus Hale?'),
                   ('Did you leave?', 'Did you leave your room at any point last night?')],
        mock_lines={
            "truthful": "Twelve years of service, Detective. I keep this house in order.",
            "deflect": "I really couldn't say. You might consider the caretaker's hours.",
            "lie": "I retired to my room at nine and did not leave it.",
            "crack": "Very well. I left for the village at ten. It was a matter of family debt, nothing more.",
        },
    ),
    "clara": Suspect(
        id="clara", name="Clara Ashworth",
        persona="The victim's wife, composed and icy, answers questions with questions.",
        facts=("Wife of Mr. Ashworth. Says she was reading in the library from 9pm "
               "(cover story). Last saw her husband at dinner at 8pm."),
        secret="She burned a letter in the library at 10:40pm: her plan to leave him before he changed his will.",
        guilty=False,
        seed_memories=["I told the police I was reading in the library all evening.",
                       "I last saw my husband at dinner at 8pm."],
        followups=[('The marriage', 'How was your marriage with Mr. Ashworth?'),
                   ('Press the alibi', 'Did anyone see you in the library last night, Mrs. Ashworth?'),
                   ('The will', 'Did your husband say anything about changing his will?'),
                   ('The fireplace', 'Did you use the library fireplace last night?')],
        mock_lines={
            "truthful": "We dined at eight. He was in good spirits. Why do you ask?",
            "deflect": "Is it usual to question a widow like this, Detective?",
            "lie": "I was in the library with a book. All evening.",
            "crack": "There was a letter. I burned it. It was mine, and it was private.",
        },
    ),
    "tobias": Suspect(
        id="tobias", name="Tobias Reed",
        persona="Nervy nephew and heir, talks too fast, jokes when scared.",
        facts=("Nephew of Mr. Ashworth, staying at the manor. Says he was in the billiard room "
               "from 9pm to 11pm (cover story). Visited his uncle at 4pm for tea."),
        secret="He asked Ashworth for money at 4pm and was refused; he owes gambling debts.",
        guilty=False,
        seed_memories=["I told everyone I was playing billiards alone until eleven.",
                       "I had tea with my uncle at 4pm."],
        followups=[('Billiards alibi', 'Tobias, can anyone confirm you were in the billiard room?'),
                   ('The game', 'What did you play in the billiard room, and for how long?'),
                   ('Tea with uncle', 'What did you and your uncle talk about at tea?'),
                   ('Money trouble', 'Are you in any financial trouble, Tobias?')],
        mock_lines={
            "truthful": "Tea with Uncle at four, billiards after. Riveting, I know.",
            "deflect": "Ha! Shouldn't you be asking the caretaker? Gloomy fellow.",
            "lie": "Billiards. Alone. Nine to eleven. Ask the table.",
            "crack": "Fine, I asked him for money. He said no. But I didn't touch him!",
        },
    ),
}

# kind -> id -> (short description for Decider, finding, suspect it bears on or None)
# Findings are added to the detective's notebook AND to every suspect's memory.
CASE = {
    "evidence": {
        "muddy_boots": ("muddy boots by the servants' door",
                        "Coal dust on the study carpet matches the boiler room.", "marcus"),
        "burnt_letter": ("scorched paper in the library fireplace",
                         "A burnt fragment in the library grate reads: '...leaving you...'", "clara"),
        "pawn_ticket": ("pawn shop ticket found in a coat pocket",
                        "A pawn ticket dated 10:05pm for a silver candlestick.", "eleanor"),
        "debt_notice": ("crumpled letter from a gambling club",
                        "A final demand for 2,000 pounds addressed to Tobias Reed.", "tobias"),
    },
    "logs": {
        "boiler_log": ("boiler room maintenance log",
                       "Boiler log: valve checked 9:00pm, then no entry until 11:50pm.", "marcus"),
        "wage_ledger": ("estate wage ledger",
                        "Ledger: Hale has not been paid for three weeks.", "marcus"),
        "visitor_log": ("gate visitor and staff log",
                        "Gate log: Voss signed out at 10:00pm and back in at 10:50pm.", "eleanor"),
    },
    "rooms": {
        "study": ("the study where the victim was found",
                  "The study: overturned chair, a wage ledger on the desk.", None),
        "billiard_room": ("the billiard room where Tobias says he spent the evening",
                          "The billiard room: balls still racked, chalk undisturbed, a cue rack thick with dust. Nobody has played tonight.", "tobias"),
        "library": ("the library fireplace and shelves",
                    "The library: a cold grate with scraps of burnt paper.", None),
        "boiler_room": ("the boiler room and servants' door",
                        "The boiler room: coal dust, and muddy boots near the servants' door.", None),
    },
}
