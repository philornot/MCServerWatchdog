# Wytyczne dla kontrybucji

## Konwencje commitów

Nasz projekt używa konwencji commitów, aby automatycznie generować changelog przy nowych wydaniach. Prawidłowo sformatowany commit pozwoli na automatyczne przyporządkowanie Twojej zmiany do odpowiedniej kategorii.

### Format wiadomości commita

Każda wiadomość commita powinna mieć jeden z następujących formatów:

```
<typ>: <opis>
```

lub

```
[<typ>] <opis>
```

lub

```
(<typ>) <opis>
```

gdzie `<typ>` to jeden z typów zdefiniowanych poniżej, a `<opis>` to krótki opis zmian.

### Typy commitów

| Typ | Kategoria | Opis | Emoji |
|-----|-----------|------|-------|
| `fix` | Poprawki błędów | Naprawa błędu w kodzie | 🐛 |
| `feat` | Nowe funkcje | Dodanie nowej funkcjonalności | ✨ |
| `docs` | Dokumentacja | Zmiany w dokumentacji | 📚 |
| `style` | Formatowanie kodu | Zmiany formatowania, białych znaków, itp. (bez zmian w logice) | 💎 |
| `refactor` | Refaktoryzacja | Przebudowa kodu bez zmiany funkcjonalności | ♻️ |
| `perf` | Optymalizacja | Zmiany zwiększające wydajność | 🚀 |
| `test` | Testy | Dodanie lub modyfikacja testów | 🧪 |
| `build` | Build | Zmiany w systemie budowania, zależnościach | 🔧 |
| `ci` | CI/CD | Zmiany w konfiguracji CI/CD | 🤖 |
| `chore` | Porządki | Rutynowe zadania, porządkowanie kodu | 🧹 |

(CI/CD - Continuous Integration/Continuous Deployment, m. in. GitHub Actions)
### Przykłady

```
feat: dodanie obsługi nowej komendy /status
```

```
[fix] naprawiono błąd parsowania odpowiedzi z API
```

```
(docs) aktualizacja instrukcji instalacji
```

```
refactor: przepisanie logiki sprawdzania statusu serwera
```

### Zasady tworzenia dobrych wiadomości commitów

1. **Używaj trybu rozkazującego** — pisz tak, jakbyś wydawał polecenie: "dodaj", "napraw", "zmień" itp.
2. **Bądź zwięzły** — pierwsza linia nie powinna przekraczać 72 znaków
3. **Bądź szczegółowy** — wyjaśnij co i dlaczego, a nie jak (to widać w kodzie)
4. **Używaj angielskiego lub polskiego konsekwentnie** — wybierz jeden język i trzymaj się go

### Commity, które nie pasują do kategorii

Jeśli Twój commit nie pasuje do żadnej z powyższych kategorii, zostanie automatycznie dodany do sekcji "Inne zmiany" w changelogu.

## Proces release'u

System automatycznie generuje changelog i inkrementuje wersję zgodnie z typem wydania:

- **patch** — drobne poprawki (zwiększa X.Y.Z, gdzie Z++, np. 1.0.0 -> 1.0.1)
- **minor** — nowe funkcje bez naruszania kompatybilności (zwiększa X.Y.0, gdzie Y++, np. 1.0.0 -> 1.1.0)
- **major** — zmiany łamiące kompatybilność (zwiększa X.0.0, gdzie X++, np. 1.0.0 -> 2.0.0)
---

<3