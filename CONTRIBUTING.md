# 📝 _Sugestie_ co do commitów

## 🔄 Konwencje commitów

Dla czystej rozrywki philornot ten projekt używa konwencji commitów, aby automatycznie generować changelog przy nowych
wydaniach. Prawidłowo sformatowany commit pozwoli na automatyczne przyporządkowanie Twojej zmiany do odpowiedniej
kategorii.

### 📋 Format wiadomości commita

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

### 🔖 Typy commitów

| Typ        | Kategoria         | Opis                                                           | Emoji |
|------------|-------------------|----------------------------------------------------------------|-------|
| `fix`      | Poprawki błędów   | Naprawa błędu w kodzie                                         | 🐛    |
| `feat`     | Nowe funkcje      | Dodanie nowej funkcjonalności                                  | ✨     |
| `docs`     | Dokumentacja      | Zmiany w dokumentacji                                          | 📚    |
| `style`    | Formatowanie kodu | Zmiany formatowania, białych znaków, itp. (bez zmian w logice) | 💎    |
| `refactor` | Refaktoryzacja    | Przebudowa kodu bez zmiany funkcjonalności                     | ♻️    |
| `perf`     | Optymalizacja     | Zmiany zwiększające wydajność                                  | 🚀    |
| `test`     | Testy             | Dodanie lub modyfikacja testów                                 | 🧪    |
| `build`    | Build             | Zmiany w systemie budowania, zależnościach                     | 🔧    |
| `ci`       | CI/CD             | Zmiany w konfiguracji CI/CD                                    | 🤖    |
| `chore`    | Porządki          | Rutynowe zadania, porządkowanie kodu                           | 🧹    |

(CI/CD - Continuous Integration/Continuous Deployment, m. in. GitHub Actions)

### 💡 Przykłady

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

### ✅ Zasady tworzenia dobrych wiadomości commitów

1. **Bądź zwięzły** — pierwsza linia nie powinna przekraczać 72 znaków
2. **Bądź szczegółowy** — wyjaśnij co i dlaczego, a nie jak (to widać w kodzie)
3. **Używaj angielskiego lub polskiego konsekwentnie** — wybierz jeden język i trzymaj się go

### 🔀 Commity, które nie pasują do kategorii

Jeśli Twój commit nie pasuje do żadnej z powyższych kategorii, zostanie automatycznie dodany do sekcji "Inne zmiany" w
changelogu.

## 🚀 Proces release'u

System automatycznie generuje changelog i inkrementuje wersję zgodnie z typem wydania:

| Typ            | Opis                                        | Wersjonowanie                          | Przykład              | Oznaczenie                   |
|----------------|---------------------------------------------|----------------------------------------|-----------------------|------------------------------|
| **prerelease** | Wydania testowe/rozwojowe                   | Bez inkrementacji, tylko dodanie hasha | 1.0.0 → 1.0.0+7f3a2d1 | ⚠️ Oznaczone jako prerelease |
| **patch**      | Drobne poprawki                             | X.Y.Z → X.Y.(Z+1)                      | 1.0.0 → 1.0.1         | ✅ Pełne wydanie              |
| **minor**      | Nowe funkcje bez naruszania kompatybilności | X.Y.Z → X.(Y+1).0                      | 1.0.0 → 1.1.0         | ✅ Pełne wydanie              |
| **major**      | Zmiany łamiące kompatybilność               | X.Y.Z → (X+1).0.0                      | 1.0.0 → 2.0.0         | ✅ Pełne wydanie              |

### 📦 Wersje prerelease

Wydania prerelease są przeznaczone do testów i wczesnego dostępu. Są oznaczone hashiem commita i flagą prerelease w
GitHub.

<img alt="Diagram wersjonowania" height="512" src="https://www.mermaidchart.com/raw/80bf72f4-f7a7-4251-9a16-cdf8ede1eeda?theme=light&amp;amp;amp;version=v0.1&amp;amp;amp;format=svg" width="1024"/>

---

<3