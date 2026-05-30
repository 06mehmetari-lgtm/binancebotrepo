import neat
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "neat.config")

class NEATEngine:
    def __init__(self, eval_func):
        self.config = neat.Config(
            neat.DefaultGenome,
            neat.DefaultReproduction,
            neat.DefaultSpeciesSet,
            neat.DefaultStagnation,
            CONFIG_PATH,
        )
        self.eval_func = eval_func

    def run(self, generations: int = 50):
        pop = neat.Population(self.config)
        pop.add_reporter(neat.StdOutReporter(True))
        winner = pop.run(self.eval_func, generations)
        return winner
