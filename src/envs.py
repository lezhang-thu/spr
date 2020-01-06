# -*- coding: utf-8 -*-
from collections import deque
import random
import atari_py
import cv2
from .ram_annotations import atari_dict

import torch


class Env():
    def __init__(self, args):
        self.device = args.device
        self.ale = atari_py.ALEInterface()
        self.ale.setInt('random_seed', args.seed)
        self.ale.setInt('max_num_frames_per_episode', args.max_episode_length)
        self.ale.setFloat('repeat_action_probability', 0.25)  # Disable sticky actions
        self.ale.setInt('frame_skip', 0)
        self.ale.setBool('color_averaging', False)
        self.ale.loadROM(atari_py.get_game_path(args.game))  # ROM loading must be done after setting options
        actions = self.ale.getMinimalActionSet()
        self.actions = dict([i, e] for i, e in zip(range(len(actions)), actions))
        self.lives = 0  # Life counter (used in DeepMind training)
        self.life_termination = False  # Used to check if resetting only from loss of life
        self.window = args.framestack  # Number of frames to concatenate
        self.state_buffer = deque([], maxlen=args.framestack)
        self.training = True  # Consistent with model training mode
        self.grayscale = args.grayscale

    def _get_state(self):
        if self.grayscale:
            obs = self.ale.getScreenGrayscale()
        else:
            obs = self.ale.getScreenRGB()
        state = cv2.resize(obs, (96, 96), interpolation=cv2.INTER_LINEAR)
        return torch.tensor(state, dtype=torch.float32, device=self.device).div_(255)

    def _reset_buffer(self):
        if self.grayscale:
            blank = torch.zeros(96, 96, 1, device=self.device)
        else:
            blank = torch.zeros(96, 96, 3, device=self.device)
        for _ in range(self.window):
            self.state_buffer.append(blank)

    def reset(self):
        if self.life_termination:
            self.life_termination = False  # Reset flag
            self.ale.act(0)  # Use a no-op after loss of life
        else:
            # Reset internals
            self._reset_buffer()
            self.ale.reset_game()
            # Perform up to 30 random no-ops before starting
            for _ in range(random.randrange(30)):
                self.ale.act(0)  # Assumes raw action 0 is always no-op
                if self.ale.game_over():
                    self.ale.reset_game()
        # Process and return "initial" state
        observation = self._get_state()
        self.state_buffer.append(observation)
        self.lives = self.ale.lives()
        return torch.stack(list(self.state_buffer), 0)

    def step(self, action):
        # Repeat action 4 times, max pool over last 2 frames
        if self.grayscale:
            channels = 1
        else:
            channels = 3
        frame_buffer = torch.zeros(2, 96, 96, channels, device=self.device)
        reward, done = 0, False
        for t in range(4):
            reward += self.ale.act(self.actions.get(action))
            if t == 2:
                frame_buffer[0] = self._get_state()
            elif t == 3:
                frame_buffer[1] = self._get_state()
            done = self.ale.game_over()
            if done:
                break
        observation = frame_buffer.max(0)[0]
        self.state_buffer.append(observation)
        # Detect loss of life as terminal in training mode
        if self.training:
            lives = self.ale.lives()
            if lives < self.lives and lives > 0:  # Lives > 0 for Q*bert
                self.life_termination = not done  # Only set flag when not truly done
                done = True
            self.lives = lives
        # Return state, reward, done
        return torch.stack(list(self.state_buffer), 0), reward, done

    # Uses loss of life as terminal signal
    def train(self):
        self.training = True

    # Uses standard terminal signal
    def eval(self):
        self.training = False

    def action_space(self):
        return len(self.actions)

    def render(self, mode='rgb_array'):
        if mode == 'rgb_array':
            return self._get_image()
        cv2.imshow('screen', self.ale.getScreenRGB()[:, :, ::-1])
        cv2.waitKey(1)

    def close(self):
        cv2.destroyAllWindows()

    def _get_image(self):
        return self.ale.getScreenRGB2()


class AARIEnv(Env):
    def __init__(self, args):
        super().__init__(args)
        self.env_name = args.game
        self.game_name = self.env_name.replace("_", "").lower()#split("-")[0].split("No")[0].split("Deterministic")[0]
        assert self.game_name in atari_dict, "{} is not currently supported by AARI. It's either not an Atari game or we don't have the ram annotations yet!".format(self.game_name)

    def info(self, info):
        label_dict = self.labels()
        info["labels"] = label_dict
        return info

    def step(self, action):
        states, rewards, done = super().step(action)
        labels = self.labels()
        info = {"labels": labels}
        return states, rewards, done, info

    def labels(self):
        ram = self.ale.getRAM()
        label_dict = ram2label(self.game_name, ram)
        return label_dict


def ram2label(game_name, ram):
    if game_name.lower() in atari_dict:
        label_dict = {k: ram[ind] for k, ind in atari_dict[game_name.lower()].items()}
    else:
        assert False, "{} is not currently supported by AARI. It's either not an Atari game or we don't have the ram annotations yet!".format(game_name)
    return label_dict


