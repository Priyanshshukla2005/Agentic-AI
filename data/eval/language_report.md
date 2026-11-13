# Language evaluation (plan_v5)

Generated 2026-11-13 09:48 with `mock/mock`, TRANSLATE_MODE=`auto`, sample profiles [0, 1].

| Language | Mode | Script match | WRONG_LANGUAGE | NUMBER_MISMATCH | Passed validation | Avg seconds |
|---|---|---|---|---|---|---|
| English | direct | 100% | 0/2 | 0/2 | 1/2 | 5.1 |
| Hindi (हिन्दी) | direct | 99% | 0/2 | 0/2 | 1/2 | 0.1 |
| Bengali (বাংলা) | pivot | 0% | 2/2 | 0/2 | 0/2 | 0.1 |
| Marathi (मराठी) | pivot | 0% | 2/2 | 0/2 | 0/2 | 0.1 |
| Tamil (தமிழ்) | pivot | 0% | 2/2 | 0/2 | 0/2 | 0.1 |
| Telugu (తెలుగు) | pivot | 0% | 2/2 | 0/2 | 0/2 | 0.1 |
| Gujarati (ગુજરાતી) | pivot | 0% | 2/2 | 0/2 | 0/2 | 0.0 |

Script match = share of letters written in the expected script (Devanagari for Hindi/Marathi, Bengali, Tamil, Telugu, Gujarati, Latin for English). Below 60% counts as WRONG_LANGUAGE.
Mock mode only has English and Hindi plans and cannot translate, so the other languages are expected to show WRONG_LANGUAGE here. Run with Groq for real numbers.
