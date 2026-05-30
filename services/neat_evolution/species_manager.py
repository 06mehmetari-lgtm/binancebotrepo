class SpeciesManager:
    def __init__(self):
        self.species: dict[int, list] = {}

    def update(self, species_set):
        self.species = {
            sid: [g.key for g in members]
            for sid, members in species_set.species.items()
        }

    def stats(self) -> dict:
        return {
            "count": len(self.species),
            "sizes": {sid: len(m) for sid, m in self.species.items()},
        }
