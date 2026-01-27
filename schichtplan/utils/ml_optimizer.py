def _calculate_assignment_score(self, ma, datum, wunsch, fairness, bereits_geplant):
    """Berechnet Score mit 7 Kategorien"""
    score = 100.0
    
    # === KATEGORIE 1: URLAUB (MUSS respektiert werden) ===
    if wunsch and wunsch.wunsch == 'urlaub':
        if wunsch.genehmigt:
            return -1000  # NIEMALS zuweisen
        else:
            return -500   # Nicht genehmigt, trotzdem vermeiden
    
    # === KATEGORIE 6: GAR NICHTS (MUSS respektiert werden) ===
    if wunsch and wunsch.wunsch == 'gar_nichts':
        if wunsch.genehmigt:
            return -1000  # NIEMALS zuweisen
        else:
            return -500
    
    # === KATEGORIE 2: KEIN TAG, ABER NACHT ===
    if wunsch and wunsch.wunsch == 'kein_tag_aber_nacht':
        # Wenn Tagschicht geprüft wird → sehr niedriger Score
        if self._ist_tagschicht_berechnung(datum):
            score -= 200  # Fast unmöglich
        else:
            score += 50   # Nachtschicht bevorzugen
    
    # === KATEGORIE 3: KEINE NACHT, ABER TAG ===
    if wunsch and wunsch.wunsch == 'keine_nacht_aber_tag':
        # Wenn Nachtschicht geprüft wird → sehr niedriger Score
        if self._ist_nachtschicht_berechnung(datum):
            score -= 200  # Fast unmöglich
        else:
            score += 50   # Tagschicht bevorzugen
    
    # === KATEGORIE 4: TAG BEVORZUGT ===
    if wunsch and wunsch.wunsch == 'tag_bevorzugt':
        if self._ist_tagschicht_berechnung(datum):
            score += 30  # Bonus für Wunscherfüllung
        else:
            score -= 10  # Kleiner Malus wenn Nacht
    
    # === KATEGORIE 5: NACHT BEVORZUGT ===
    if wunsch and wunsch.wunsch == 'nacht_bevorzugt':
        if self._ist_nachtschicht_berechnung(datum):
            score += 30  # Bonus für Wunscherfüllung
        else:
            score -= 10  # Kleiner Malus wenn Tag
    
    # === KATEGORIE 7: ZUSATZARBEIT ===
    if wunsch and wunsch.wunsch == 'zusatzarbeit':
        score += 40  # Höherer Bonus - will arbeiten!
        # Zusätzlich: Fairness weniger wichtig
        if fairness.get('gesamt_schichten', 0) > fairness.get('soll_schichten', 0):
            score += 20  # Hat schon viel, aber will mehr → OK!
    
    # Rest der Fairness-Berechnung...
    # (wie vorher)
    
    return score


def _bestimme_schichttyp(self, ma, datum, wunsch):
    """Bestimmt T oder N basierend auf Wunsch"""
    
    # Harte Constraints
    if wunsch:
        if wunsch.wunsch == 'kein_tag_aber_nacht':
            return 'N'  # NUR Nacht möglich
        elif wunsch.wunsch == 'keine_nacht_aber_tag':
            return 'T'  # NUR Tag möglich
        elif wunsch.wunsch == 'tag_bevorzugt':
            return 'T'  # Präferenz Tag
        elif wunsch.wunsch == 'nacht_bevorzugt':
            return 'N'  # Präferenz Nacht
        elif wunsch.wunsch == 'zusatzarbeit':
            # Bei Zusatzarbeit: Was braucht Team mehr?
            return self._was_wird_mehr_gebraucht(datum)
    
    # Sonst aus Historie lernen
    return self._predict_shift_type_from_history(ma, datum)